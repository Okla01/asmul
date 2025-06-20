import html as std_html
import mimetypes
from hashlib import md5
from html import escape
from aiogram import types, F
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from admins.filters.allowed_ids import AllowedIDs
from config import dp, bot, report_questions_from_candidates_chat_id, new_cand_request_chat_id, SIM_NAMES
from db.database import *
from db.database import _get_basic_user
from user.registration.keyboards import *
from user.registration.utils.llm_answer import answer
from user.registration.states import *
from user.registration.utils.phone_meta import build_phone_display, safe_result_id

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"}


def is_image(path: str) -> bool:
    """Проверяем по расширению или MIME-типу, является ли файл изображением."""
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTS:
        return True
    ctype, _ = mimetypes.guess_type(path)
    return bool(ctype and ctype.startswith("image"))


async def smart_send(chat_id: int, file_path_or_id: str, caption: str):
    """
    Если это картинка — send_photo, иначе — send_document.
    file_path_or_id может быть локальным путем или Telegram file_id.
    """
    if Path(file_path_or_id).exists():
        media = FSInputFile(file_path_or_id)
        is_img = is_image(file_path_or_id)
    else:
        media = file_path_or_id
        is_img = False
    if is_img:
        return await bot.send_photo(chat_id=chat_id, photo=media, caption=caption)

    try:
        return await bot.send_document(chat_id=chat_id, document=media, caption=caption)
    except TelegramBadRequest as e:
        if "can't use file of type Photo as Document" in str(e):
            return await bot.send_photo(chat_id=chat_id, photo=media, caption=caption)

    raise


async def _user_lang(state: FSMContext) -> str:
    data = await state.get_data()
    return data.get("lang", "ru")


# ------------------------------------------------------------------
# 1.  /start  -------------------------------------------------------
# ------------------------------------------------------------------
@dp.message(Command("start"))
async def start_message(message: types.Message, state: FSMContext):
    if str(message.chat.id).startswith("-"):
        return  # игнорируем группы

    user_id = message.from_user.id
    username = message.from_user.username
    tg_full_name = message.from_user.full_name

    # обновляем / создаём запись пользователя
    if user_exists(user_id):
        db_user_update(user_id, username, tg_full_name)
        from db.database import is_stage1_complete, is_stage2_complete
        
        if is_stage2_complete(user_id):
            # Пользователь полностью зарегистрирован - переходим в главное меню
            from user.auth.handlers import user_main_menu_kb
            await bot.send_message(
                message.chat.id,
                tr("ru", "welcome_back"),
                reply_markup=user_main_menu_kb
            )
            return
        elif is_stage1_complete(user_id):
            # Пользователь прошел только первый этап - показываем меню stage2 с текущими статусами
            lang = get_user_lang(user_id)
            completed = is_stage2_complete(user_id)
            await bot.send_message(
                message.chat.id,
                tr(lang, "continue_registration_stage2") + "\n\n" + stage2_intro_text(lang, user_id),
                parse_mode="HTML",
                reply_markup=build_stage2_kb(lang, completed)
            )
            return
    else:
        db_user_insert(id=user_id, username=username, tg_full_name=tg_full_name)

    # Если пользователь не начал регистрацию, показываем выбор языка
    await state.set_state()
    await bot.send_message(
        message.chat.id,
        tr("ru", "choose_language_prompt"),
        reply_markup=LANG_KB,
    )
    await state.update_data(general_msg_id=message.message_id)


# ------------------------------------------------------------------
# 2.  выбор языка ---------------------------------------------------
# ------------------------------------------------------------------
@dp.callback_query(F.data.startswith("lang_"))
async def callback_query_choose_language(callback_query: CallbackQuery, state: FSMContext):
    lang = callback_query.data.split("_", 1)[1]
    user_id = callback_query.from_user.id
    
    # Обновляем язык пользователя
    set_user_lang(user_id, lang)
    
    # Проверяем, завершил ли пользователь регистрацию
    if is_stage2_complete(user_id):
        # Пользователь уже зарегистрирован - переходим в главное меню
        from user.auth.handlers import user_main_menu_kb
        await callback_query.message.edit_text(
            tr(lang, "welcome_back"),
            parse_mode="HTML",
            reply_markup=user_main_menu_kb
        )
        await state.clear()
        return
        
    # Если регистрация не завершена, продолжаем процесс
    await state.update_data(lang=lang)
    await callback_query.message.edit_text(
        tr(lang, "welcome_message"),
        parse_mode="HTML",
        reply_markup=build_participant_kb(lang),
    )


@dp.callback_query(F.data == "back_1_1")
async def back_auth_h(callback_query: CallbackQuery, state: FSMContext):
    await state.set_state()
    lang = get_user_lang(callback_query.from_user.id)
    await callback_query.message.edit_text(
        tr(lang, "welcome_message"),
        parse_mode="HTML",
        reply_markup=build_participant_kb(lang),
    )
    await callback_query.answer()


# ------------------------------------------------------------------
# 3.  Регистрация участницы ----------------------------------------
# ------------------------------------------------------------------
@dp.callback_query(F.data == "become_participant")
async def callback_query_become_participant(callback_query: CallbackQuery, state: FSMContext):
    lang = get_user_lang(callback_query.from_user.id)
    msg_id = callback_query.message.message_id

    await state.update_data(general_msg_id=msg_id)
    await state.set_state(RegistrationForm.WaitForFIO)

    await callback_query.message.edit_text(tr(lang, "fio_prompt"), reply_markup=build_back_1_1_kb(lang))
    await callback_query.answer()


# ---------- ФИО ----------------------------------------------------
@dp.message(F.text, RegistrationForm.WaitForFIO)
async def process_fio(message: Message, state: FSMContext):
    lang = get_user_lang(message.from_user.id)
    fio = message.text.strip()
    data = await state.get_data()
    gen_id = data["general_msg_id"]

    if len(fio.split()) < 2:
        try:
            await bot.send_message(
                chat_id=message.chat.id,
                text=tr(lang, "fio_invalid"),
            )
        except Exception:
            pass
        return

    await state.update_data(fio=fio)
    await state.set_state(RegistrationForm.WaitForGender)
    await bot.send_message(
        chat_id=message.chat.id,
        text=tr(lang, "gender_prompt"),
        reply_markup=build_gender_kb(lang),
    )


# обратно
@dp.message(F.text, RegistrationForm.WaitForFIO)
async def process_fio_back(message: Message, state: FSMContext):
    lang = get_user_lang(message.from_user.id)
    await state.set_state(RegistrationForm.WaitForGender)
    await bot.send_message(
        chat_id=message.chat.id,
        text=tr(lang, "gender_prompt"),
        reply_markup=build_gender_kb(lang),
    )


# ---------- пол ----------------------------------------------------
@dp.callback_query(RegistrationForm.WaitForGender, F.data.startswith("gender_"))
async def process_gender_callback(callback_query: CallbackQuery, state: FSMContext):
    lang = get_user_lang(callback_query.from_user.id)
    if callback_query.data == "gender_male":
        await bot.send_message(callback_query.message.chat.id, tr(lang, "male_not_eligible"),
                               reply_markup=build_gender_male_kb(lang))
        await callback_query.answer()
        return

    # сохраняем пол и переходим к выбору страны
    await state.update_data(gender="female")

    await state.set_state(RegistrationForm.WaitForCountry)

    msg = await callback_query.message.answer(
        tr(lang, "country_prompt"),
        reply_markup=build_country_search_kb(lang)
    )
    # запомним id этого сообщения, чтобы потом редактировать
    await state.update_data(country_msg_id=msg.message_id)
    await callback_query.answer()


# контакты поддержки
@dp.callback_query(RegistrationForm.WaitForGender, F.data == "btn_support_contacts")
async def support_contacts_h(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    lang = get_user_lang(cb.message.from_user.id)
    await state.set_state(RegistrationForm.WaitForGender)
    await cb.message.answer(
        text=tr(lang, "support_contacts"),
        reply_markup=delete_this_msg_cand(lang),
    )


@dp.inline_query(RegistrationForm.WaitForCountry)
async def inline_country(iq: types.InlineQuery, state: FSMContext):
    lang = get_user_lang(iq.from_user.id)

    query = iq.query.lstrip()
    if query.lower().startswith("country:"):
        query = query[8:].lstrip()

    if len(query) == 0:
        countries = COUNTRY_LIST[lang]
        # Если ввёл меньше 2 символов — не ищем
    elif len(query) < 2:
        return await iq.answer([], cache_time=1)
        # Иначе фильтруем по подстроке
    else:
        countries = [c for c in COUNTRY_LIST[lang] if query.lower() in c.lower()]

    if not countries:
        return await iq.answer(
            [],
            cache_time=1,
            switch_pm_text="Не найдено",
            switch_pm_parameter="country_not_found"
        )

    results = []
    for idx, name in enumerate(countries[:50], start=1):
        safe_id = f"cnt_{idx}_{md5(name.encode()).hexdigest()[:8]}"  # <=64 & ascii
        results.append(
            types.InlineQueryResultArticle(
                id=safe_id,
                title=name,
                input_message_content=types.InputTextMessageContent(
                    message_text=f"#CNT:{name}"
                )
            )
        )
    await iq.answer(results, cache_time=1)


@dp.message(RegistrationForm.WaitForCountry, F.text.startswith("#CNT:"))
async def country_chosen(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id)
    country = msg.text[5:].strip()

    await state.update_data(country=country)

    code, mask = get_meta_by_country(country)  # («+7», «___ ___-__-__»)
    await state.update_data(phone_code=code, phone_mask=mask)

    # редактируем сообщение «Страна: …»
    data = await state.get_data()
    prompt_id = data.get("country_msg_id")
    if prompt_id:
        await bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=prompt_id,
            text=f"{tr(lang, 'label_country')}: <b>{std_html.escape(country)}</b>",
            parse_mode="HTML"
        )
    await msg.delete()

    # переходим к телефону
    await state.set_state(RegistrationForm.WaitForPhone)
    m = await bot.send_message(
        msg.chat.id,
        tr(lang, "phone_prompt"),
        reply_markup=build_phone_kb(code, lang)
    )
    await state.update_data(phone_msg_id=m.message_id)


# ---------- телефон ------------------------------------------------
@dp.inline_query(RegistrationForm.WaitForPhone)
async def inline_phone(iq: types.InlineQuery, state: FSMContext):
    st = await state.get_data()
    code = st.get("phone_code", "+")
    mask = st.get("phone_mask", "__________")

    query = iq.query.removeprefix("phone:").strip()
    # ---------- ➋ проверяем, не ввёл ли пользователь ДРУГОЙ код ----
    m = re.match(r"^\+(\d{1,4})", query)  # до 4 цифр после «+»
    if m:
        digits_in_query = m.group(1)  # «224123…»
        # ищем самый длинный префикс, который есть в CODE_MASK
        new_code = None
        for end in range(len(digits_in_query), 0, -1):
            candidate = "+" + digits_in_query[:end]
            if candidate in CODE_MASK:
                new_code = candidate
                break

        if new_code and new_code != code:
            code = new_code
            mask = CODE_MASK[code]
            await state.update_data(phone_code=code, phone_mask=mask)

    # --------- ➌ убираем сам код из строки и оставляем «хвост» -----
    clean = re.sub(rf"^\+?{re.escape(code.lstrip('+'))}", "", query)
    digits = re.sub(r"\D", "", clean)

    display = build_phone_display(code, digits, mask)
    res_id = safe_result_id(code, digits)

    await iq.answer([
        types.InlineQueryResultArticle(
            id=res_id,
            title=display,
            input_message_content=types.InputTextMessageContent(
                message_text=f"#PHN:{code}{digits}"
            )
        )
    ], cache_time=5)


@dp.message(RegistrationForm.WaitForPhone, F.text.startswith("#PHN:"))
async def phone_saved(msg: Message, state: FSMContext):
    lang = get_user_lang(msg.from_user.id)
    phone = msg.text[5:].strip()
    digits = re.sub(r"\D", "", phone)

    st = await state.get_data()
    mask_len = st.get("phone_mask", "__________").count("_")
    err_cnt = st.get("phone_error_count", 0)
    old_err_id = st.get("phone_error_msg_id")
    old_user_msg_id = st.get("phone_error_user_id")  # 

    # ─── удаляем прошлые сообщения (ошибка + невалидный ввод) ───
    for mid in (old_err_id, old_user_msg_id):  # 
        if mid:
            try:
                await bot.delete_message(msg.chat.id, mid)
            except Exception:
                pass
    if old_err_id or old_user_msg_id:  # 
        await state.update_data(phone_error_msg_id=None,
                                phone_error_user_id=None)

    if len(digits) < mask_len:
        err_cnt += 1
        await state.update_data(phone_error_count=err_cnt)

        key = "phone_too_short_double" if err_cnt > 1 else "phone_too_short"
        err = await msg.answer(tr(lang, key))

        # сохраняем id текущих «ошибочных» сообщений
        await state.update_data(
            phone_error_msg_id=err.message_id,
            phone_error_user_id=msg.message_id  # 
        )
        return

    # ─── всё ок ────────────────────────────────────────────────
    await state.update_data(
        phone=phone,
        phone_error_count=0,
        phone_error_msg_id=None,
        phone_error_user_id=None  # 
    )

    if (pid := st.get("phone_msg_id")):
        await bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=pid,
            text=f"{tr(lang, 'label_phone')}: <b>{std_html.escape(phone)}</b>",
            parse_mode="HTML"
        )

    await msg.delete()

    await state.set_state(RegistrationForm.WaitForEmail)
    email_prompt = await bot.send_message(msg.chat.id, tr(lang, "email_prompt"))
    await state.update_data(email_msg_id=email_prompt.message_id)


# ---------- email --------------------------------------------------
@dp.message(RegistrationForm.WaitForEmail, F.text)
async def process_email(message: Message, state: FSMContext):
    import html as std_html  # 
    lang = get_user_lang(message.from_user.id)
    email = message.text.strip()
    email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"

    data = await state.get_data()
    err_cnt = data.get("email_error_count", 0)
    old_err_id = data.get("email_error_msg_id")
    old_user_msg_id = data.get("email_error_user_id")
    email_msg_id = data.get("email_msg_id")  # 

    # ─── удаляем прошлые ошибки и невалидный ввод ───
    for mid in (old_err_id, old_user_msg_id):
        if mid:
            try:
                await bot.delete_message(message.chat.id, mid)
            except Exception:
                pass
    if old_err_id or old_user_msg_id:
        await state.update_data(email_error_msg_id=None,
                                email_error_user_id=None)

    # ─── проверка ───
    if not re.match(email_regex, email):
        err_cnt += 1
        await state.update_data(email_error_count=err_cnt)

        key = "email_invalid_double" if err_cnt > 1 else "email_invalid"
        err = await bot.send_message(message.chat.id, tr(lang, key))

        await state.update_data(
            email_error_msg_id=err.message_id,
            email_error_user_id=message.message_id
        )
        return

    # ─── e-mail валиден ───
    await state.update_data(
        email=email,
        email_error_count=0,
        email_error_msg_id=None,
        email_error_user_id=None
    )

    # 
    if email_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=email_msg_id,
                text=f"{tr(lang, 'label_email')}: <b>{std_html.escape(email)}</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass
        await state.update_data(email_msg_id=None)

    await message.delete()
    await state.set_state(RegistrationForm.WaitForAge)
    await bot.send_message(message.chat.id, tr(lang, "age_prompt"))


# ---------- возраст ------------------------------------------------
@dp.message(F.text, RegistrationForm.WaitForAge)
async def process_age(message: Message, state: FSMContext):
    lang = get_user_lang(message.from_user.id)
    age_str = message.text.strip()
    data = await state.get_data()
    gen_id = data["general_msg_id"]
    # ─ проверка, что ввод — число
    if not age_str.isdigit():
        # await message.delete()
        try:
            await bot.send_message(
                chat_id=message.chat.id,
                text=tr(lang, "age_not_number"),
            )
        except Exception:
            pass
        return
    age = int(age_str)

    # ─ определяем допустимый диапазон
    country = data.get("country") or ""
    if is_cis(country, lang):
        min_age, max_age = 16, 22  # для стран СНГ
    else:
        min_age, max_age = 18, 23  # для остальных

    if age < min_age or age > max_age:
        # await message.delete()
        try:
            await bot.send_message(
                chat_id=message.chat.id,
                text=tr(lang, "age_invalid"),
            )
        except Exception:
            pass
        return
    # ─ всё ок, сохраняем возраст
    await state.update_data(age=age)
    # await message.delete()

    data = await state.get_data()
    summary_text = (
            tr(lang, "summary_header")
            + f"<b>{tr(lang, 'label_fio')}</b>: {data.get('fio')}\n"
            + f"<b>{tr(lang, 'label_gender')}</b>: {tr(lang, 'btn_gender_female')}\n"
            + f"<b>{tr(lang, 'label_country')}</b>: {data.get('country')}\n"
            + f"<b>{tr(lang, 'label_phone')}</b>: {data.get('phone')}\n"
            + f"<b>{tr(lang, 'label_email')}</b>: {data.get('email')}\n"
            + f"<b>{tr(lang, 'label_age')}</b>: {data.get('age')}\n\n"
            + tr(lang, "summary_confirm_question")
    )

    await bot.send_message(
        chat_id=message.chat.id,
        text=summary_text,
        reply_markup=build_apply_reg_kb(lang),
        parse_mode="HTML",
    )
    await state.set_state(RegistrationForm.WaitForConfirm)


# ---------- подтверждение данных ----------------------------------
@dp.callback_query(RegistrationForm.WaitForConfirm, F.data == "confirm_registration")
async def confirm_data(callback_query: CallbackQuery, state: FSMContext):
    lang = get_user_lang(callback_query.from_user.id)
    data = await state.get_data()

    # сохраняем в БД
    db_user_update_full(
        telegram_id=callback_query.from_user.id,
        full_name=data.get("fio"),
        gender=data.get("gender"),
        country=data.get("country"),
        phone_number=data.get("phone"),
        email=data.get("email"),
        age=data.get("age"),
    )
    general_msg_id = data.get("general_msg_id")
    list_messages_ids = list(range(general_msg_id, callback_query.message.message_id + 1))
    await bot.delete_messages(chat_id=callback_query.message.chat.id, message_ids=list_messages_ids)
    completed = is_stage2_complete(callback_query.from_user.id)  # False на этом шаге
    await callback_query.message.answer(
        tr(lang, "data_saved") + "\n\n" + stage2_intro_text(lang, callback_query.from_user.id),
        parse_mode="HTML",
        reply_markup=build_stage2_kb(lang, completed),  # 
    )
    await state.set_state()
    await callback_query.answer()


# ---------- изменить данные ---------------------------------------
@dp.callback_query(RegistrationForm.WaitForConfirm, F.data == "change_data")
async def change_data(callback_query: CallbackQuery, state: FSMContext):
    lang = get_user_lang(callback_query.from_user.id)
    await state.set_state(RegistrationForm.WaitForFIO)
    await callback_query.message.edit_text(tr(lang, "fio_prompt"))
    await callback_query.answer()


# ------------------------------------------------------------------
# 4.  Меню Stage 2 --------------------------------------------------
# ------------------------------------------------------------------

@dp.callback_query(F.data == "go_stage_2")
async def go_stage_2(callback_query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("messages_to_delete") is not None:
        await bot.delete_messages(chat_id=callback_query.message.chat.id,
                                  message_ids=data.get("messages_to_delete") + [data.get("general_msg_id")]
                                  )
    await state.set_data({})
    lang = get_user_lang(callback_query.from_user.id)
    await state.set_state()
    completed = is_stage2_complete(callback_query.from_user.id)  # 
    notified = is_notifed(callback_query.from_user.id)
    if completed and not notified:
        full_name, username = _get_basic_user(callback_query.from_user.id)
        text = (
            f" Новая заявка от участницы\n"
            f" {full_name}\n"
            f" @{username}\n"
            f" {callback_query.from_user.id}"
        )
        await bot.send_message(
            chat_id=new_cand_request_chat_id,
            text=text,
            reply_markup=get_claim_kb(callback_query.from_user.id)
        )
        # пометим, что уведомили
        set_notifed(callback_query.message.chat.id, True)
    try:
        await callback_query.message.edit_text(
            stage2_intro_text(lang, callback_query.from_user.id),
            parse_mode="HTML",
            reply_markup=build_stage2_kb(lang, completed),  # 
        )
    except Exception:
        await callback_query.message.delete()
        msg = await bot.send_message(
            chat_id=callback_query.message.chat.id,
            text=stage2_intro_text(lang, callback_query.from_user.id),
            parse_mode="HTML",
            reply_markup=build_stage2_kb(lang, completed),
        )
        await state.update_data(general_msg_id=msg.message_id)

    await callback_query.answer()


@dp.message(Command("go_stage_2"), AllowedIDs())
async def go_stage_2_h(message: Message, state: FSMContext):
    await message.answer("stage_2", reply_markup=build_stage2_1_back_kb("ru"))


# ---------- 2.1  фото ---------------------------------------------
@dp.callback_query(F.data == "go_stage_2.1")
async def go_stage_2_1(callback_query: CallbackQuery, state: FSMContext):
    if is_stage2_complete(callback_query.from_user.id):
        return
    lang = get_user_lang(callback_query.from_user.id)
    await callback_query.message.delete()
    country = get_user_card_data_by_id(user_id=callback_query.from_user.id).get("country")
    photo_url = get_photo_example_url(country, lang)
    await callback_query.message.answer(
        text=tr(lang, "photo_instruction", photo_path=photo_url),
        reply_markup=build_stage2_1_back_kb(lang),
        parse_mode="HTML"
    )
    await state.update_data(general_msg_id=callback_query.message.message_id)
    await state.set_state(RegistrationForm.WaitForPhoto)
    await callback_query.answer()


ALLOWED_MIME = ("image/jpeg", "image/png")


@dp.message(StateFilter(RegistrationForm.WaitForPhoto), F.photo | (F.document & F.document.mime_type.in_(ALLOWED_MIME)))
async def process_photo(message: Message, state: FSMContext):
    lang = get_user_lang(message.from_user.id)
    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document:
        file_id = message.document.file_id

    if not file_id:
        await message.reply(tr(lang, "attach_file_prompt"))
        return

    add_user_document(
        user_id=message.from_user.id,
        document_type="photo",
        file_path=file_id,
    )

    # await message.delete()
    data = await state.get_data()
    gen_id = data["general_msg_id"]
    messages_to_delete = data.get("messages_to_delete")
    messages_to_delete = [message.message_id] if messages_to_delete is None else messages_to_delete + [
        message.message_id]
    await state.update_data(messages_to_delete=messages_to_delete)
    await bot.send_message(
        chat_id=message.chat.id,
        text=tr(lang, "photo_attached"),
        reply_markup=build_stage2_1_continue_kb(lang),
    )
    await state.set_state()


# ---------- 2.2  паспорт ------------------------------------------
@dp.callback_query(F.data == "go_stage_2.2")
async def back_to_passport_choice(callback_query: CallbackQuery, state: FSMContext):
    if is_stage2_complete(callback_query.from_user.id):
        return
    lang = get_user_lang(callback_query.from_user.id)
    await callback_query.message.edit_text(
        tr(lang, "passport_question"),
        reply_markup=build_passport_choice_kb(lang),
    )
    await state.update_data(general_msg_id=callback_query.message.message_id)
    await state.set_state(RegistrationForm.WaitForPassportChoice)
    await callback_query.answer()


@dp.callback_query(RegistrationForm.WaitForPassportChoice)
async def passport_choice(callback_query: CallbackQuery, state: FSMContext):
    lang = get_user_lang(callback_query.from_user.id)
    choice = callback_query.data  # has_passport / no_passport

    if choice == "has_passport":
        await callback_query.message.delete()
        await callback_query.message.answer(
            text=tr(lang, "passport_attach"),
            reply_markup=build_stage2_1_back_kb(lang),
            parse_mode="HTML"
        )
        await state.set_state(RegistrationForm.WaitForPassportAttach)
    else:
        data = await state.get_data()
        messages_to_delete = data.get("messages_to_delete")
        messages_to_delete = [
            callback_query.message.message_id] if messages_to_delete is None else messages_to_delete + [
            callback_query.message.message_id]
        await state.update_data(messages_to_delete=messages_to_delete)
        await callback_query.message.edit_text(
            tr(lang, "passport_reason_prompt"),
            reply_markup=build_passport_reason_kb(lang),
        )
        await state.set_state(RegistrationForm.WaitForPassportReason)
    await callback_query.answer()


# причины отсутствия паспорта
REASON_KEY = {
    "reason_wait": "btn_reason_wait",
    "reason_money": "btn_reason_money",
    "reason_other": "btn_reason_other",
}


@dp.callback_query(RegistrationForm.WaitForPassportReason)
async def passport_reason(callback_query: CallbackQuery, state: FSMContext):
    lang = get_user_lang(callback_query.from_user.id)
    reason_code = callback_query.data

    add_user_document(
        user_id=callback_query.from_user.id,
        document_type="passport",
        file_path=None,
        reason_of_absence=reason_code,
    )

    reason_text = tr(lang, REASON_KEY[reason_code])
    await callback_query.message.edit_text(
        tr(lang, "passport_reason_accepted", reason=reason_text),
        reply_markup=build_stage2_1_continue_kb(lang),
        parse_mode="HTML",
    )
    await callback_query.answer()


# прикрепление паспорта
@dp.message(RegistrationForm.WaitForPassportAttach, F.photo | (F.document & F.document.mime_type.in_(ALLOWED_MIME)))
async def process_passport_attachment(message: Message, state: FSMContext):
    lang = get_user_lang(message.from_user.id)
    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document:
        file_id = message.document.file_id

    if not file_id:
        await message.reply(tr(lang, "attach_file_prompt"))
        return
    messages_to_delete = (await state.get_data()).get("messages_to_delete")
    messages_to_delete = [message.message_id] if messages_to_delete is None else messages_to_delete + [
        message.message_id]
    await state.update_data(passport_file_id=file_id, messages_to_delete=messages_to_delete)

    add_user_document(
        user_id=message.from_user.id,
        document_type="passport",
        file_path=file_id,
    )

    # await message.delete()

    await bot.send_message(
        chat_id=message.chat.id,
        text=tr(lang, "passport_attached"),
        reply_markup=build_stage2_1_continue_kb(lang),
    )
    await state.set_state()


# ---------- 2.3  симуляции ----------------------------------------
@dp.callback_query(F.data == "go_stage_2.3")
async def simulation_complete(callback_query: CallbackQuery, state: FSMContext):
    if is_stage2_complete(callback_query.from_user.id):
        return
    lang = get_user_lang(callback_query.from_user.id)
    await callback_query.message.edit_text(
        tr(lang, "simulation_intro"),
        reply_markup=build_sim_as_vs_kb(lang),
    )
    await callback_query.answer()


@dp.callback_query(F.data == "sim_as")
async def sim_as_h(callback_query: CallbackQuery, state: FSMContext):
    lang = get_user_lang(callback_query.from_user.id)
    await callback_query.message.delete()
    await callback_query.message.answer(
        text=tr(lang, "sim_as_prompt"),
        reply_markup=build_stage2_1_back_kb(lang),
        parse_mode="HTML"
    )
    await state.update_data(general_msg_id=callback_query.message.message_id)
    await state.set_state(RegistrationForm.WaitForASMIR)
    await callback_query.answer()


@dp.message(RegistrationForm.WaitForASMIR, F.photo | (F.document & F.document.mime_type.in_(ALLOWED_MIME)))
async def sim_as_h_photo(message: Message, state: FSMContext):
    lang = get_user_lang(message.from_user.id)
    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document:
        file_id = message.document.file_id

    if not file_id:
        await message.reply(tr(lang, "attach_file_prompt"))
        return

    add_simulation_result(
        user_id=message.from_user.id, simulation_type="AS_MIR", screenshot_path=file_id
    )

    await state.update_data(as_mir_file_id=file_id)
    await message.delete()
    await state.set_state()

    data = await state.get_data()
    gen_id = data["general_msg_id"]
    try:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=gen_id,
            text=tr(lang, "sim_thanks"),
            reply_markup=build_stage2_1_continue_kb(lang),
        )
    except:
        msg = await message.answer(text=tr(lang, "sim_thanks"),
                                   reply_markup=build_stage2_1_continue_kb(lang))
        await state.update_data(general_msg_id=msg.message_id)


@dp.callback_query(F.data == "sim_vs")
async def sim_vs_h(callback_query: CallbackQuery, state: FSMContext):
    lang = get_user_lang(callback_query.from_user.id)
    await callback_query.message.delete()
    await callback_query.message.answer(
        text=tr(lang, "sim_vs_prompt"),
        reply_markup=build_stage2_1_back_kb(lang),
        parse_mode="HTML"
    )
    await state.update_data(general_msg_id=callback_query.message.message_id)
    await state.set_state(RegistrationForm.WaitForVSMIR)
    await callback_query.answer()


@dp.message(RegistrationForm.WaitForVSMIR, F.photo | (F.document & F.document.mime_type.in_(ALLOWED_MIME)))
async def sim_vs_h_photo(message: Message, state: FSMContext):
    lang = get_user_lang(message.from_user.id)
    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document:
        file_id = message.document.file_id

    if not file_id:
        await message.reply(tr(lang, "attach_file_prompt"))
        return

    add_simulation_result(
        user_id=message.from_user.id, simulation_type="VS_MIR", screenshot_path=file_id
    )

    await state.update_data(vs_mir_file_id=file_id)
    await message.delete()
    await state.set_state()

    data = await state.get_data()
    gen_id = data["general_msg_id"]

    try:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=gen_id,
            text=tr(lang, "sim_thanks"),
            reply_markup=build_stage2_1_continue_kb(lang),
        )
    except:
        msg = await message.answer(text=tr(lang, "sim_thanks"),
                                   reply_markup=build_stage2_1_continue_kb(lang))
        await state.update_data(general_msg_id=msg.message_id)


# ------------------------------------------------------------------
#  2.4 «Задать вопрос»
# ------------------------------------------------------------------
@dp.callback_query(F.data == "go_stage_2.4")
async def ask_question_start(callback_query: CallbackQuery, state: FSMContext):
    lang = get_user_lang(callback_query.from_user.id)
    # сразу переходим в состояние ожидания вопроса для LLM
    await state.set_state(AskQuestionForm.WaitingForQuestionForLLM)
    await callback_query.message.edit_text(
        tr(lang, "ask_neuro_prompt"),  # теперь другой текст
        reply_markup=build_cancel_question_kb(lang),
    )
    await state.update_data(general_msg_id=callback_query.message.message_id)
    await callback_query.answer()


# ----------- отмена вопроса ---------------------------------------
@dp.callback_query(StateFilter(AskQuestionForm.WaitingForQuestion, AskQuestionForm.WaitingForQuestionForLLM),
                   F.data == "cancel_question")
async def ask_question_cancel(callback_query: CallbackQuery, state: FSMContext):
    lang = get_user_lang(callback_query.from_user.id)
    await callback_query.message.edit_text(
        tr(lang, "ask_cancelled"),
        reply_markup=build_stage2_kb(lang, is_stage2_complete(callback_query.from_user.id)),  # 
    )
    await state.clear()
    await callback_query.answer()


# ----------- пользователь отправил текст вопроса -------------------
@dp.message(F.text, AskQuestionForm.WaitingForQuestionForLLM)
async def process_user_question_llm(message: Message, state: FSMContext):
    await bot.send_chat_action(message.from_user.id, ChatAction.TYPING)
    await answer(message)


# ------------------------------------------------------------------
#             АДМИНСКАЯ ЧАСТЬ  (группа report_questions_from_candidates_chat_id)
# ------------------------------------------------------------------
@dp.callback_query(F.data.startswith("admin_reply_cand_"))
async def admin_reply_cand_start(callback_query: CallbackQuery, state: FSMContext):
    admin = callback_query.from_user
    user_id = int(callback_query.data.split("_")[3])

    # Заполняем state администратора
    await state.set_state(AdminReplyFormCand.WaitingForReplyText)
    await state.update_data(
        user_id=user_id,
        admin_msg_id=callback_query.message.message_id,
        original_text=callback_query.message.text,
    )

    # Обновляем сообщение в группе
    new_text = (
        f"{callback_query.message.text}\n\n"
        f" ⏳ <b>{escape(admin.full_name)}</b> пишет ответ..."
    )
    await bot.edit_message_text(
        chat_id=report_questions_from_candidates_chat_id,
        message_id=callback_query.message.message_id,
        text=new_text,
        parse_mode="HTML",
    )
    await callback_query.answer("Напишите ответ (первым сообщением)")


@dp.message(AdminReplyFormCand.WaitingForReplyText)
async def admin_process_reply(msg: Message, state: FSMContext):
    if msg.chat.id != report_questions_from_candidates_chat_id:
        return  # защита: сообщение не из нужной группы

    data = await state.get_data()
    user_id = data["user_id"]
    admin_msg_id = data["admin_msg_id"]
    original_text = data["original_text"]
    answer_admin = msg.text
    admin = msg.from_user

    # 1. Пробуем отправить ответ пользователю
    delivered = True
    try:
        await bot.send_message(
            chat_id=user_id,
            text=f"✉️ Ответ от администратора:\n\n{escape(answer_admin)}",
        )
    except TelegramForbiddenError:
        delivered = False

    # 2. Обновляем сообщение в группе, убираем клаву
    admin_info = f"{escape(admin.full_name)}"
    if admin.username:
        admin_info += f" (@{admin.username})"

    group_text = (
        f"{original_text}\n\n"
        f"✅ <b>Ответ отправлен:</b>\n{escape(answer_admin)}\n\n"
        f"👤 <b>Ответил:</b> {admin_info}"
    )
    if not delivered:
        group_text += "\n\n<tg-spoiler>⚠️ Пользователь не получил ответ (заблокировал бота)</tg-spoiler>"

    await bot.edit_message_text(
        chat_id=report_questions_from_candidates_chat_id,
        message_id=admin_msg_id,
        text=group_text,
        parse_mode="HTML",
        reply_markup=None,
    )
    # await bot.delete_message(chat_id=report_questions_from_candidates_chat_id, message_id=msg.message_id)
    await state.clear()


# ------------- Stage‑3 (открываем меню, страница 0) ----------------
@dp.callback_query(F.data == "go_stage_3")
async def info_root(callback_query: CallbackQuery, state: FSMContext):
    lang = get_user_lang(callback_query.from_user.id)
    if not INFO_DATA.get(lang):
        await callback_query.answer(tr(lang, "no_info"), show_alert=True)
        return
    await callback_query.message.edit_text(
        f"<b>{tr(lang, 'info_menu_title')}</b>",
        parse_mode="HTML",
        reply_markup=build_info_menu_kb(lang, 0),
    )
    await callback_query.answer()


# ------------- перелистывание страниц ------------------------------
@dp.callback_query(F.data.startswith("info_page_"))
async def info_turn_page(cb: CallbackQuery, state: FSMContext):
    lang = get_user_lang(cb.from_user.id)
    page = int(cb.data.split("_")[2])
    await cb.message.edit_text(
        f"<b>{tr(lang, 'info_menu_title')}</b>",
        parse_mode="HTML",
        reply_markup=build_info_menu_kb(lang, page),
    )
    await cb.answer()


@dp.callback_query(F.data == "info_nop")
async def info_nop(cb: CallbackQuery):
    # просто закрываем «часики»
    await cb.answer()


# ------------- показ статьи ----------------------------------------
@dp.callback_query(F.data.startswith("info_show_"))
async def info_show_article(callback_query: CallbackQuery, state: FSMContext):
    lang = get_user_lang(callback_query.from_user.id)
    _, _, idx, page = callback_query.data.split("_")
    idx, page = int(idx), int(page)
    try:
        title, body = INFO_DATA[lang][idx]
    except IndexError:
        await callback_query.answer("⚠️ not found", show_alert=True)
        return

    # делим длинные тексты на 4000‑симв. части
    parts = [body[i:i + 4000] for i in range(0, len(body), 4000)]
    header = f"<b>{escape(title)}</b>\n\n"

    await callback_query.message.edit_text(
        header + parts[0],
        parse_mode="HTML",
        reply_markup=build_back_to_info_kb(lang, page),
    )
    for chunk in parts[1:]:
        await bot.send_message(callback_query.message.chat.id, chunk)
    await callback_query.answer()


@dp.callback_query(F.data == "delete_this_msg_cand")
async def delete_this_msg_cand_h(callback_query: CallbackQuery):
    await callback_query.message.delete()


@dp.callback_query(F.data.startswith("admin_claim_user_"))
async def admin_claim(callback_query: CallbackQuery):
    admin = callback_query.from_user
    user_id = int(callback_query.data.split("_")[-1])

    # 1) Убираем кнопку в админ-чате
    await bot.edit_message_reply_markup(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        reply_markup=None
    )
    # 2) Обновляем текст сообщения
    new_text = (
            f"{callback_query.message.text}\n\n"
            f"✅ Заявка взята в работу: <b>{std_html.escape(admin.full_name)}</b>"
            + (f" (@{admin.username})" if admin.username else "")
    )
    await bot.edit_message_text(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        text=new_text,
        parse_mode="HTML"
    )
    await callback_query.answer("Вы взяли эту заявку")

    # 3) Собираем и отправляем данные пользователя в ЛС админу
    # 3.1 Базовая информация
    full_name, username = _get_basic_user(user_id)
    cursor.execute(
        "SELECT phone_number, email, country, age FROM users WHERE user_id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    phone, email, country, age = row["phone_number"] or "-", row["email"] or "-", row["country"] or "-", row[
        "age"] or "-"

    profile_text = (
        "<b> 📋 Данные кандидата:</b>\n"
        f" 👤 {std_html.escape(full_name)}\n"
        f" 🔗 @{username}\n"
        f" 📞 {phone}\n"
        f" ✉️ {email}\n"
        f"{country}\n"
        f"{age}\n"
    )
    await bot.send_message(
        chat_id=admin.id,
        text=profile_text,
        parse_mode="HTML"
    )

    # 3.2 Все файлы из user_documents (photo, passport, …)
    cursor.execute("SELECT document_type, file_path FROM user_documents WHERE user_id = ?", (user_id,))
    for doc_type, file_path in cursor.fetchall():
        caption = {
            "photo": "Фото кандидата",
            "passport": "Скан паспорта",
        }.get(doc_type, doc_type.capitalize())
        await smart_send(admin.id, file_path, caption)

    # 4) Отправляем скриншоты симуляций из simulations
    cursor.execute("SELECT simulation_type, screenshot_path FROM simulations WHERE user_id = ?", (user_id,))
    for sim_type, screenshot in cursor.fetchall():
        caption = f"Симуляция: {SIM_NAMES[sim_type]}"
        await smart_send(admin.id, screenshot, caption)
