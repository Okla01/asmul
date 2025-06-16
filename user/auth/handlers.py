import tempfile

from PIL import Image
from aiogram import F, html, types
from aiogram.exceptions import TelegramForbiddenError, TelegramAPIError, TelegramBadRequest
from aiogram.filters import StateFilter, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InputMediaPhoto
from aiogram_dialog import DialogManager, StartMode
from aiogram_media_group import media_group_handler

from admins.filters.allowed_ids import AllowedIDs
from config import *
from db.database import *
from user.auth.keyboards import *
from user.auth.other_func import create_collage, build_user_card_text, is_event_open, trp
from user.auth.states import *


@dp.message(F.text == "/", AllowedIDs())
async def aaa(message: Message, state: FSMContext):
    await state.set_state()
    await message.answer(
        trp(key="welcome_root"),
        reply_markup=user_main_menu_kb
    )


@dp.callback_query(F.data == "already_participant")
async def auth_h(cb: CallbackQuery, state: FSMContext):
    uid = cb.from_user.id

    # есть ли запись с ролью «участница»?
    participant_row = cursor.execute(
        "SELECT 1 FROM users WHERE user_id=? AND role='user_participant' LIMIT 1",
        (uid,)
    ).fetchone()

    if participant_row:  # ✅  известная участница – открываем главное меню
        await cb.answer(trp("welcome_callback"))
        await cb.message.edit_text(
            trp("already_authorized"),
            reply_markup=user_main_menu_kb
        )
        return

    # ⬇️   пользователь НЕ найден как участница – спрашиваем ФИО
    await state.set_state(AuthForm.WaitForFIO)
    await state.update_data(auth_message_id=cb.message.message_id)
    await cb.message.edit_text(
        trp("prompt_enter_fio"),
        reply_markup=stage_1_1_kb
    )
    await cb.answer()


@dp.message(AuthForm.WaitForFIO)
async def auth_process_fio(msg: Message, state: FSMContext):
    fio = msg.text.strip()
    uid = msg.from_user.id
    uname = f"@{msg.from_user.username}" if msg.from_user.username else "—"

    # ищем кандидата по ФИО
    from db.database import search_users_by_fio
    matches = search_users_by_fio(fio, limit=1)
    fio_exists = bool(matches)
    candidate_old_id = matches[0]["id"] if fio_exists else None

    exist_label = (
        trp("label_found_in_db")
        if fio_exists
        else trp("label_not_in_db")
    )

    text = trp("admin_request_fio_text").format(
        fio=fio,
        exist_label=exist_label,
        uname=uname,
        uid=uid
    )

    kb = InlineKeyboardBuilder()

    if fio_exists:  # ──▶ показываем «Подтвердить» ТОЛЬКО если запись есть
        kb.button(
            text=trp("btn_confirm_candidate"),
            callback_data=f"bot_access_ok_{uid}_{candidate_old_id}"
        )
    else:  # ──▶ заменяем кнопку подсказкой
        text += "\n\n" + trp("admin_fio_not_found_warning")

    kb.button(
        text=trp("btn_reject_candidate"),
        callback_data=f"bot_access_reject_{uid}"
    )
    admin_kb = kb.adjust(1).as_markup()

    await bot.send_message(
        request_bot_user_chat_id,
        text,
        reply_markup=admin_kb,
        parse_mode="HTML"
    )

    await msg.answer(
        trp("user_request_sent")
    )
    await state.clear()


@dp.callback_query(F.data.startswith("bot_access_ok_"))
async def grant_bot_access(cb: CallbackQuery):
    """
    Переносим user_id от временной записи к существующей карточке по ФИО.
    Шаги:
      1) удаляем «временного» пользователя с id =new_если он есть;
      2) обновляем найденную по ФИО запись (old_id) -> new_uid;
      3) помечаем bot_user=1 и сохраняем username.
    """
    m = re.match(r"bot_access_ok_(\d+)_(\d+)", cb.data)
    if not m:
        await cb.answer(trp("auth_incorrect_data"), show_alert=True)
        return

    new_uid, old_id = map(int, m.groups())
    uname = cb.from_user.username or ""

    # ➊ удаляем возможную временную запись
    cursor.execute("DELETE FROM users WHERE user_id = ?", (new_uid,))

    # ➋ переносим ID
    if old_id != new_uid:
        cursor.execute("""
                UPDATE users
                   SET user_id = ?, username = ?, bot_user = 1
                 WHERE user_id = ?
            """, (new_uid, uname, old_id))
    else:  # id уже совпал – просто активируем
        cursor.execute("""
                UPDATE users
                   SET username = ?, bot_user = 1
                 WHERE user_id = ?
            """, (uname, new_uid))

    conn.commit()

    # ➌ уведомляем
    await bot.send_message(new_uid, trp("access_confirmed_user"))
    await cb.message.edit_reply_markup()
    await cb.message.edit_text(
        cb.message.text + "\n\n" + trp("access_confirmed_user"),
        parse_mode="HTML"
    )
    await cb.answer(trp("admin_event_approve_text"))


@dp.callback_query(F.data.startswith("bot_access_reject_"))
async def reject_bot_access(cb: CallbackQuery):
    uid = int(cb.data.split("_")[-1])
    await bot.send_message(trp("access_rejected_user"))
    await cb.message.edit_reply_markup()
    await cb.message.edit_text(
        cb.message.text + "\n\n" + trp("access_rejected_user"),
        parse_mode="HTML"
    )
    await cb.answer(trp("admin_event_reject_text"))


@dp.callback_query(F.data == "user_main_faq")
async def user_main_faq_handler(callback_query: CallbackQuery):
    await callback_query.answer()
    try:
        await callback_query.message.edit_text(
            text=trp("faq_choose_question"),
            reply_markup=await get_faq_for_user(
                load_faq_from_db(callback_query.from_user.id)
            )
        )
    except:
        await callback_query.answer(
            trp("faq_unavailable_role"),
            show_alert=True
        )


@dp.callback_query(F.data == "ask_admin_question")
async def ask_admin_start(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    await state.set_state(AskAdminForm.WaitingForQuestion)
    await callback_query.message.edit_text(
        trp("ask_admin_write_question"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=trp("btn_cancel_question"),
                    callback_data="cancel_question"
                )
            ]
        ])
    )
    await state.update_data(general_msg_id=callback_query.message.message_id)


@dp.callback_query(F.data == "cancel_question", AskAdminForm.WaitingForQuestion)
async def cancel_question(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    await state.clear()
    await callback_query.message.edit_text(
        trp("question_cancelled"),
        reply_markup=user_main_menu_kb
    )


# Получение вопроса от пользователя и отправка админам
@dp.message(AskAdminForm.WaitingForQuestion)
async def process_admin_question(message: Message, state: FSMContext):
    await state.set_state()  # Очищаем состояние пользователя

    user = message.from_user
    question_text = message.text

    # Формируем основную часть сообщения
    user_info = f"Пользователь: {html.quote(user.full_name)}"
    if user.username:
        user_info += f" (@{user.username})"
    user_info += f"\nID: {user.id}"

    base_admin_message_text = trp(
        "admin_question_template"
    ).format(
        user_info=user_info,
        question_text=html.quote(question_text)
    )

    forward_error_text = ""
    try:
        # Попытка переслать оригинал ДО отправки основного сообщения
        await bot.forward_message(
            chat_id=report_questions_from_users_chat_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            disable_notification=False
        )
    except TelegramForbiddenError:
        forward_error_text = "\n\n" + trp("admin_forward_error")
    except Exception as e:
        forward_error_text = "\n\n" + trp(
            "admin_forward_error_generic"
        ).format(error=e)

    # Собираем финальный текст для админов
    admin_message_text = base_admin_message_text + forward_error_text

    # Отправляем сообщение админам с кнопкой
    await bot.send_message(
        chat_id=report_questions_from_users_chat_id,
        text=admin_message_text,
        parse_mode="HTML",
        reply_markup=get_admin_reply_kb(user.id)
    )
    # await message.delete()
    # Уведомляем пользователя
    await bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=(await state.get_data())["general_msg_id"],
        text=trp("thanks_question_sent"),
        reply_markup=user_main_menu_kb
    )


@dp.callback_query(F.data.startswith("admin_reply_us_"))
async def admin_start_reply(callback_query: CallbackQuery, state: FSMContext):
    admin_user = callback_query.from_user  # Админ, который нажал кнопку

    user_id_to_reply = int(callback_query.data.split("_")[3])
    admin_chat_message_id = callback_query.message.message_id  # ID сообщения с кнопкой
    original_admin_text = callback_query.message.text  # Исходный текст в админ-чате
    original_admin_entities = callback_query.message.entities  # Исходная разметка

    # Устанавливаем состояние для админа, нажавшего кнопку
    await state.set_state(AdminReplyFormAuth.WaitingForReplyText)
    # Сохраняем нужные данные в state
    await state.update_data(
        user_id_to_reply=user_id_to_reply,
        admin_chat_message_id=admin_chat_message_id,
        original_admin_text=original_admin_text,
        original_admin_entities=original_admin_entities  # Сохраняем для восстановления при отмене
    )

    # Редактируем сообщение в группе, убираем кнопку и добавляем пометку
    admin_info = f"{html.quote(admin_user.full_name)}"
    if admin_user.username:
        admin_info += f" (@{admin_user.username})"

    # Новый текст с пометкой об ответе
    text_while_replying = (
        original_admin_text
        + "\n\n"
        + trp("admin_is_writing_reply").format(admin_info=admin_info)
    )

    await bot.edit_message_text(
        chat_id=report_questions_from_users_chat_id,
        message_id=admin_chat_message_id,
        text=text_while_replying,
        parse_mode="HTML",
        reply_markup=None
    )

    # Отвечаем на callback_query, чтобы кнопка перестала "грузиться"
    await callback_query.answer(
        trp("admin_reply_prompt").format(
            user_id_to_reply=user_id_to_reply
        )
    )


@dp.callback_query(Command("cancel_admin_reply"), AdminReplyFormAuth.WaitingForReplyText)
async def admin_cancel_reply_cmd(message: Message, state: FSMContext):
    data = await state.get_data()
    admin_chat_message_id = data.get("admin_chat_message_id")
    original_admin_text = data.get("original_admin_text")
    user_id_to_reply = data.get("user_id_to_reply")  # Нужен для восстановления кнопки

    if not all([admin_chat_message_id, original_admin_text is not None, user_id_to_reply]):
        await message.answer(trp("admin_cancel_reply_error"))
        await state.clear()
        return

    try:
        # Возвращаем исходный текст и кнопку "Ответить"
        await bot.edit_message_text(
            chat_id=report_questions_from_users_chat_id,
            message_id=admin_chat_message_id,
            text=original_admin_text,
            parse_mode="HTML",
            reply_markup=get_admin_reply_kb(user_id_to_reply)
        )
        await message.answer(trp("admin_cancel_reply_success"))
    except Exception:
        await message.answer(trp("admin_cancel_reply_error"))

    await state.clear()


@dp.message(F.text, AdminReplyFormAuth.WaitingForReplyText)
async def admin_process_reply(message: Message, state: FSMContext):
    # Убедимся, что сообщение пришло из админской группы (на всякий случай)
    if message.chat.id != report_questions_from_users_chat_id:
        return

    admin_reply_text = message.text  # Текст ответа админа из группы
    admin_user = message.from_user

    data = await state.get_data()
    user_id_to_reply = data.get("user_id_to_reply")
    admin_chat_message_id = data.get("admin_chat_message_id")
    original_admin_text = data.get("original_admin_text")

    if not all([user_id_to_reply, admin_chat_message_id, original_admin_text is not None]):
        await message.reply(
            trp("admin_forward_error_generic").format(error="не найдены данные")
        )
        return

    # 1. Отправляем ответ пользователю
    try:
        await bot.send_message(
            chat_id=user_id_to_reply,
            text=trp("user_received_admin_reply").format(
                admin_info=html.quote(admin_user.full_name),
                reply_text=html.quote(admin_reply_text)
            )
        )
        user_notified = True
    except TelegramForbiddenError:
        await message.reply(trp("admin_reply_group_update_error"))
        user_notified = False

    # 2. Редактируем исходное сообщение в админской группе (на которое нажимали "Ответить")
    try:
        admin_info = f"{html.quote(admin_user.full_name)}"
        if admin_user.username:
            admin_info += f" (@{admin_user.username})"

        updated_admin_text = (
            original_admin_text
            + "\n\n"
            + trp("admin_updated_caption_prefix").format(
                reply_text=html.quote(admin_reply_text),
                admin_info=admin_info
            )
        )
        if not user_notified:
            updated_admin_text += "\n\n<tg-spoiler>" + trp(
                "admin_reply_group_update_error"
            ) + "</tg-spoiler>"

        await bot.edit_message_text(
            chat_id=report_questions_from_users_chat_id,
            message_id=admin_chat_message_id,
            text=updated_admin_text,
            parse_mode="HTML",
            reply_markup=None
        )
    finally:
        await state.clear()


@dp.callback_query(F.data.startswith("faq_select_"))
async def faq_question_handler(callback_query: CallbackQuery):
    await callback_query.answer()

    question_id_str = callback_query.data.replace("faq_select_", "")
    if not question_id_str.isdigit():
        await callback_query.message.edit_text(trp("faq_invalid_id"))
        return

    question_id = int(question_id_str)

    try:
        row = get_faq_by_id(question_id)
        if not row:
            await callback_query.message.edit_text(trp("faq_not_found"))
            return

        answer_text = f"<b>{row['question']}</b>\n\n{row['answer']}"

        await callback_query.message.edit_text(
            text=answer_text,
            reply_markup=faq_menu_kb,
            parse_mode="HTML"
        )
    except:
        await callback_query.message.edit_text(
            text=trp("faq_load_error")
        )


@dp.callback_query(F.data == "user_main_myinfo")
async def user_main_myinfo_handler(callback_query: CallbackQuery) -> None:
    await callback_query.answer(trp("loading_user_info"), show_alert=False)

    user_id = callback_query.from_user.id
    employee_id = get_tabel_number_by_user_id(user_id)
    msg = callback_query.message

    try:
        card = get_user_card_data_by_id(tabel_number=employee_id)
    except Exception as e:
        await msg.edit_text(
            trp("error_loading_user_info"),
            reply_markup=back_to_menu_kb,
        )
        print(f"[user_main_myinfo] DB error {user_id}: {e}")
        return

    if not card:
        await msg.edit_text(
            trp("user_info_not_found"),
            reply_markup=back_to_menu_kb,
        )
        return

    caption = build_user_card_text(card)
    photo_obj = get_photo_or_none(card)

    try:
        if photo_obj:
            await bot.edit_message_media(
                chat_id=msg.chat.id,
                message_id=msg.message_id,
                media=InputMediaPhoto(media=photo_obj, caption=caption, parse_mode="HTML"),
                reply_markup=back_to_menu_kb,
            )
        else:
            await msg.edit_text(caption, reply_markup=back_to_menu_kb, parse_mode="HTML")
    except TelegramAPIError:
        if photo_obj:
            await bot.send_photo(
                msg.chat.id,
                photo=photo_obj,
                caption=caption,
                parse_mode="HTML",
                reply_markup=back_to_menu_kb
            )
        else:
            await bot.send_message(
                msg.chat.id,
                caption,
                parse_mode="HTML",
                reply_markup=back_to_menu_kb
            )
        await msg.delete()


@dp.callback_query(F.data == "user_main_cleanreport")
async def user_main_cleanreport_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()

    text = trp("clean_report_prompt")
    await state.update_data(general_msg_id=callback.message.message_id)
    await callback.message.edit_text(text=text, reply_markup=back_to_menu_kb)
    await state.set_state(CleanReportStates.WaitingPhotos)


@dp.message(CleanReportStates.WaitingPhotos, F.media_group_id, F.photo)
@media_group_handler
async def handle_album(messages: List[types.Message], state: FSMContext):
    photo_ids = [m.photo[-1].file_id for m in messages]
    msg_ids = [m.message_id for m in messages]
    await _store_photos(photo_ids, msg_ids, state, messages[0])


@dp.message(CleanReportStates.WaitingPhotos, F.photo)
async def handle_single(message: types.Message, state: FSMContext):
    await _store_photos(
        [message.photo[-1].file_id],
        [message.message_id],
        state,
        message
    )


async def _store_photos(
    new_ids: list[str],
    new_msg_ids: list[int],
    state: FSMContext,
    message: types.Message,
):
    data = await state.get_data()
    photos = data.get("photos_list", [])
    photos.extend(new_ids)

    to_del = data.get("msg_ids_to_delete", [])
    to_del.extend(new_msg_ids)

    if len(photos) > 7:
        await state.update_data(
            photos_list=[],
            msg_ids_to_delete=[]
        )
        await message.answer(
            trp("error_too_many_photos")
        )
        return

    await state.update_data(
        photos_list=photos,
        msg_ids_to_delete=to_del
    )

    if len(photos) == 7:
        await cleanreport_process_and_send(message, state)


async def cleanreport_process_and_send(message: Message, state: FSMContext):
    data = await state.get_data()
    photos_list = [fid for fid in data.get("photos_list", []) if fid]
    del_msg_ids = data.get("msg_ids_to_delete", [])
    user_id = message.from_user.id

    user_info = get_user_info_by_id(user_id)
    if user_info:
        full_name, username, address, living_space, tg_full_name = user_info
    else:
        full_name, username, address, living_space, tg_full_name = ("Неизвестно", "", "", "", "")

    report_id = add_cleanliness_report(user_id=user_id, room_number=address)
    if living_space in ("ЮП", "Южный парк"):
        admin_chat_id = clean_report_yup_chat_id
    elif living_space == "Пирамида":
        admin_chat_id = clean_report_piramida_chat_id
    else:
        admin_chat_id = 0

    if admin_chat_id != 0:
        images_pil = []
        for file_id in photos_list:
            file_info = await bot.get_file(file_id)
            file_obj = await bot.download_file(file_info.file_path)
            file_obj.seek(0)
            images_pil.append(Image.open(file_obj))

        collage_img = create_collage(images_pil, cols=3, rows=3)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_file:
            collage_img.save(tmp_file, format="JPEG")
            tmp_file_path = tmp_file.name

        photo_to_send = FSInputFile(tmp_file_path)

        caption_text = (
            trp("admin_caption_report_clean_prefix").format(
                full_name=full_name,
                tg_full_name=tg_full_name,
                username=message.from_user.username or "",
                address=address or "–",
                living_space=living_space,
                report_id=report_id
            )
        )

        kb = InlineKeyboardBuilder()
        kb.button(text=trp("clean_report_status_clean"), callback_data=f"cleanreport_rate_clean_{report_id}")
        kb.button(text=trp("clean_report_status_mid"), callback_data=f"cleanreport_rate_mid_{report_id}")
        kb.button(text=trp("clean_report_status_dirty"), callback_data=f"cleanreport_rate_dirty_{report_id}")
        kb.adjust(1, 1, 1)

        sent = await bot.send_photo(
            chat_id=admin_chat_id,
            photo=photo_to_send,
            caption=caption_text,
            reply_markup=kb.as_markup()
        )

        clean_photo_id = sent.photo[-1].file_id
        cursor.execute("UPDATE room_cleanliness_reports SET file_id = ? WHERE id = ?", (clean_photo_id, report_id))
        conn.commit()

        general_msg_id = data["general_msg_id"]
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=general_msg_id,
            text=trp("user_cleanreport_sent_notification").format(report_id=report_id),
            reply_markup=user_main_menu_kb,
        )
        await state.clear()
        await state.update_data(general_msg_id=general_msg_id)
    else:
        await message.edit_text(
            trp("report_no_residence"),
            reply_markup=user_main_menu_kb
        )
    if del_msg_ids:
        try:
            await bot.delete_messages(chat_id=message.chat.id, message_ids=del_msg_ids)
        except Exception:
            for mid in del_msg_ids:
                try:
                    await bot.delete_message(chat_id=message.chat.id, message_id=mid)
                except Exception:
                    pass


@dp.callback_query(F.data.startswith("cleanreport_rate_"))
async def admin_rate_report(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    if len(parts) < 4:
        return
    rate_code = parts[2]
    report_id_str = parts[3]
    if not report_id_str.isdigit():
        return


    report_id = int(report_id_str)
    user_id = get_user_id_by_report_id(report_id)
    user_info = get_user_info_by_id(user_id)
    full_name, username, address, living_space, tg_full_name = user_info
    await callback.answer()
    if rate_code == "clean":
        update_cleanliness_report(report_id, "Чисто", "")
        await callback.message.edit_caption(
            trp("admin_caption_report_clean_prefix").format(
                full_name=full_name,
                tg_full_name=tg_full_name,
                username=username or "",
                address=address or "–",
                living_space=living_space,
                report_id=report_id
            )
        )
        if user_id:
            await bot.send_message(
                chat_id=user_id,
                text=trp("user_report_status_update_clean").format(report_id=report_id),
                reply_markup=delete_this_msg_kb
            )
    elif rate_code in ["mid", "dirty"]:
        rate_text = trp("clean_report_status_mid") if rate_code == "mid" else trp("clean_report_status_dirty")
        await state.update_data(report_id=report_id, rate_text=rate_text)
        await callback.message.edit_caption(
            trp("admin_caption_report_mid_dirty_prefix").format(
                report_id=report_id,
                rate_text=rate_text
            )
        )
        await state.update_data(report_msg_id=callback.message.message_id)
        await state.set_state(CleanReportStates.AdminWaitingComment)
    else:
        await callback.message.answer(trp("auth_incorrect_data"), reply_markup=delete_this_msg_kb)


@dp.message(CleanReportStates.AdminWaitingComment)
async def admin_rate_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    report_id = data.get("report_id")
    rate_text = data.get("rate_text", "Неизвестно")
    report_msg_id = data.get("report_msg_id")
    comment_text = message.text.strip()

    update_cleanliness_report(report_id, rate_text, comment_text)
    user_id = get_user_id_by_report_id(report_id)
    user_info = get_user_info_by_id(user_id)
    full_name, username, address, living_space, tg_full_name = user_info

    await bot.edit_message_caption(
        chat_id=message.chat.id,
        message_id=report_msg_id,
        caption=trp("admin_caption_report_mid_dirty_prefix").format(
            report_id=report_id,
            rate_text=rate_text
        ) + "\n" + f"{trp('user_report_status_update_mid_dirty').format(report_id=report_id, rate_text=rate_text, comment_text=comment_text)}"
    )

    if user_id:
        await bot.send_message(
            chat_id=user_id,
            text=trp("user_report_status_update_mid_dirty").format(
                report_id=report_id,
                rate_text=rate_text,
                comment_text=comment_text
            ),
            reply_markup=delete_this_msg_kb
        )

    await state.clear()


@dp.message(CleanReportStates.WaitingPhotos)
async def handle_not_photo(message: Message):
    await message.answer(
        trp("need_photo"),
        reply_markup=delete_this_msg_kb
    )


@dp.callback_query(F.data == "user_main_eventreport")
async def user_main_eventreport_handler(callback: CallbackQuery, state: FSMContext):
    active_events = [ev for ev in get_all_events("active") if is_event_open(ev)]
    await callback.message.edit_text(
        trp("eventreport_choose_prompt"),
        reply_markup=await get_events_keyboard(active_events)
    )
    await state.set_state(EventReportStates.ChoosingEvent)
    await callback.answer()


@dp.callback_query(F.data == "eventreport_cancel")
async def user_main_menu(callback_query: CallbackQuery, state: FSMContext):
    await state.set_state()
    await callback_query.message.edit_text(
        trp("welcome_root"),
        reply_markup=user_main_menu_kb
    )
    await callback_query.answer()


@dp.callback_query(F.data.startswith("eventreport_choose_"), EventReportStates.ChoosingEvent)
async def handle_event_choice(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    if len(parts) < 3:
        await callback.answer(trp("eventreport_invalid_data"))
        return

    event_id_str = parts[2]
    if not event_id_str.isdigit():
        await callback.answer(trp("eventreport_invalid_id_event"))
        return

    event_id = int(event_id_str)
    event_info = get_event_by_id(event_id)
    if not event_info:
        await callback.answer(trp("event_not_found"))
        return

    await callback.message.edit_text(
        trp("event_chosen_prompt").format(event_title=event_info.get("title", "Error")),
        reply_markup=back_to_choose_event_kb
    )
    await state.update_data(general_msg_id=callback.message.message_id, event_id=event_id)
    await state.set_state(EventReportStates.WaitingForPhoto)
    await callback.answer()


@dp.message(F.photo, EventReportStates.WaitingForPhoto)
async def handle_report_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    processed_group = data.get("processed_media_group_id")
    current_group = message.media_group_id

    if current_group and processed_group == current_group:
        return

    photo_file_id = message.photo[0].file_id

    if current_group:
        await state.update_data(processed_media_group_id=current_group)

    general_msg_id = data.get("general_msg_id")
    await state.update_data(report_photo_id=photo_file_id)

    await bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=general_msg_id,
        text=trp("eventphoto_received"),
        reply_markup=reports_event_kb
    )
    await state.update_data(msg_id_event_photo=message.message_id)
    await state.set_state(EventReportStates.Confirming)


@dp.callback_query(F.data == "eventreport_back")
async def user_back_to_events(callback_query: CallbackQuery, state: FSMContext):
    await state.set_state()
    data = await state.get_data()
    await bot.delete_message(chat_id=callback_query.message.chat.id,
                             message_id=data.get("msg_id_event_photo"))
    await user_main_eventreport_handler(callback_query, state)
    await callback_query.answer()


@dp.callback_query(F.data == "eventreport_confirm", EventReportStates.Confirming)
async def confirm_event_report(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    event_id = data.get("event_id")
    photo_file_id = data.get("report_photo_id")

    user_id = callback.from_user.id
    mark_user_attendance(
        event_id=event_id,
        user_id=user_id,
        attended=True,
        comment="",
        photo_id=photo_file_id
    )

    user_full_name = get_user_info_by_id(user_id)[0]
    event_info = get_event_by_id(event_id)

    text_report = trp(
        "admin_event_report_caption"
    ).format(
        event_id=event_id,
        user_full_name=user_full_name,
        tg_full_name=callback.from_user.full_name,
        username=callback.from_user.username or "",
        event_title=event_info.get("title", "Неизвестное мероприятие"),
        event_date=event_info.get("event_date", "N/A")
    )
    await bot.send_photo(
        chat_id=report_event_chat_id,
        photo=photo_file_id,
        caption=text_report,
        reply_markup=await get_event_grade_keyboard(event_id),
        parse_mode="HTML"
    )
    await bot.delete_message(chat_id=callback.message.chat.id, message_id=data.get("msg_id_event_photo"))
    await callback.message.edit_text(
        trp("event_report_sent_text"),
        reply_markup=back_to_menu_kb
    )
    await callback.answer()
    await state.clear()


@dp.callback_query(F.data.startswith("adm_approve_event_"))
async def admin_approve_report(callback: CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 4:
        return

    attendance_id_str = parts[3]
    if not attendance_id_str.isdigit():
        return

    attendance_id = int(attendance_id_str)
    admin_update_attendance(attendance_id, approved=True)

    attendance = get_attendance_by_id(attendance_id)
    if not attendance:
        return await callback.answer(trp("event_not_found"), show_alert=True)

    user_id = get_user_id_by_attendance_id(attendance_id)
    user_info = get_user_info_by_id(user_id)
    full_name = user_info[0]
    tg_username = user_info[1]
    tg_full_name = user_info[4]

    new_caption = trp(
        "admin_event_report_caption"
    ).format(
        event_id=attendance_id,
        user_full_name=full_name,
        tg_full_name=tg_full_name,
        username=tg_username,
        event_title=attendance["event_title"],
        event_date=attendance["event_date"]
    ) + "\n\n" + trp("event_user_approved").format(
        event_title=attendance["event_title"],
        attendance_id=attendance_id
    )

    await bot.send_message(
        chat_id=user_id,
        text=trp("event_user_approved").format(
            event_title=attendance["event_title"],
            attendance_id=attendance_id
        ),
        reply_markup=delete_this_msg_kb
    )
    try:
        await callback.message.edit_caption(caption=new_caption, reply_markup=None)
    except Exception:
        pass

    await callback.answer(trp("admin_event_approve_text"))


@dp.callback_query(F.data.startswith("adm_reject_event_"))
async def admin_reject_report(callback: CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 4:
        return

    attendance_id_str = parts[3]
    if not attendance_id_str.isdigit():
        return

    attendance_id = int(attendance_id_str)
    admin_update_attendance(attendance_id, approved=False)

    attendance = get_attendance_by_id(attendance_id)
    if not attendance:
        return await callback.answer(trp("event_not_found"), show_alert=True)

    user_id = get_user_id_by_attendance_id(attendance_id)
    user_info = get_user_info_by_id(user_id)
    full_name = user_info[0]
    tg_username = user_info[1]
    tg_full_name = user_info[4]

    new_caption = trp(
        "admin_event_report_caption"
    ).format(
        event_id=attendance_id,
        user_full_name=full_name,
        tg_full_name=tg_full_name,
        username=tg_username,
        event_title=attendance["event_title"],
        event_date=attendance["event_date"]
    ) + "\n\n" + trp("event_user_rejected").format(
        event_title=attendance["event_title"]
    )
    try:
        await bot.send_message(chat_id=user_id,
                               text=trp("event_user_rejected").format(event_title=attendance["event_title"]),
                               reply_markup=delete_this_msg_kb)
    except Exception:
        pass
    try:
        await callback.message.edit_caption(caption=new_caption, reply_markup=None)
    except Exception:
        pass

    await callback.answer(trp("admin_event_reject_text"))


async def edit_absence_main(state: FSMContext, text: str, kb: InlineKeyboardMarkup | None = None, parse_mode: str = "HTML"):
    data = await state.get_data()
    await bot.edit_message_text(
        chat_id=data["chat_id"],
        message_id=data["main_msg_id"],
        text=text,
        reply_markup=kb,
        parse_mode=parse_mode
    )


@dp.callback_query(F.data == "user_main_absence")
async def user_main_absence_handler(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(AbsenceFlow.ChoosingLocation)

    await cb.message.edit_text(
        trp("absence_choose_location"),
        reply_markup=await get_location_keyboard()
    )
    await state.update_data(
        main_msg_id=cb.message.message_id,
        chat_id=cb.message.chat.id,
    )
    await cb.answer()


@dp.callback_query(F.data.startswith(LOC_CALLBACK_PREFIX), AbsenceFlow.ChoosingLocation)
async def handle_loc_choice(q: CallbackQuery, state: FSMContext):
    val = q.data.removeprefix(LOC_CALLBACK_PREFIX)
    sel = set((await state.get_data()).get("locations", []))
    sel.symmetric_difference_update({val})
    await state.update_data(locations=list(sel))
    await q.message.edit_reply_markup(
        reply_markup=await get_location_keyboard(selected=list(sel))
    )
    await q.answer()


@dp.callback_query(F.data == CONFIRM_REASON_CALLBACK, AbsenceFlow.ChoosingLocation)
async def confirm_locations(q: CallbackQuery, state: FSMContext):
    if not (await state.get_data()).get("locations"):
        return await q.answer(trp("absence_select_reason_first"), show_alert=True)

    await state.set_state(AbsenceFlow.ChoosingReason)
    await q.message.edit_text(
        trp("absence_choose_reason"),
        reply_markup=await get_reason_keyboard()
    )
    await q.answer()


@dp.callback_query(F.data.startswith(REASON_CALLBACK_PREFIX), AbsenceFlow.ChoosingReason)
async def handle_reason_radio(q: CallbackQuery, state: FSMContext):
    code = q.data.removeprefix(REASON_CALLBACK_PREFIX)
    await state.update_data(reason_code=code)
    await q.message.edit_reply_markup(
        reply_markup=await get_reason_keyboard(selected=code)
    )
    await q.answer()


@dp.callback_query(F.data == CONFIRM_REASON_CALLBACK, AbsenceFlow.ChoosingReason)
async def reason_confirm(q: CallbackQuery, state: FSMContext):
    code = (await state.get_data()).get("reason_code")
    if not code:
        return await q.answer(trp("absence_select_reason_first"), show_alert=True)

    if code == "other":
        await state.set_state(AbsenceFlow.WaitingForOther)
        await q.message.edit_text(
            trp("absence_prompt_other_reason"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=trp("generic_back_button"), callback_data=BACK_CALLBACK)]
            ])
        )
    else:
        await start_file_step(state, code=code, mandatory=True)

    await q.answer()


@dp.message(AbsenceFlow.WaitingForOther, F.text)
async def save_other_text(msg: Message, state: FSMContext):
    await state.update_data(other_text=msg.text.strip())
    await msg.delete()
    await start_file_step(state, code="other")


async def start_file_step(state: FSMContext, *, code: str, mandatory: bool = True):
    await state.set_state(AbsenceFlow.DocumentUpload)
    await state.update_data(file_mandatory=mandatory, files=[])

    hints = {
        "illness": trp("absence_file_step_text_illness"),
        "family": trp("absence_file_step_text_family"),
        "vacation": trp("absence_file_step_text_vacation"),
        "other": trp("absence_file_step_text_other"),
    }
    text = trp("absence_file_prompt_generic")
    await edit_absence_main(state, text, kb=get_file_step_kb(mandatory, 0))


@dp.message(AbsenceFlow.DocumentUpload, F.document | F.photo)
async def catch_file(msg: Message, state: FSMContext):
    data = await state.get_data()
    files = data.get("files", [])

    if len(files) >= 5:
        await msg.delete()
        await msg.answer(
            trp("absence_mandatory_file_error"),
            reply_markup=get_file_step_kb(data["file_mandatory"], len(files))
        )
        return

    if msg.document:
        files.append(("doc", msg.document.file_id, msg.document.file_name or 'file'))
    else:
        files.append(("photo", msg.photo[-1].file_id, 'photo'))

    await state.update_data(files=files)
    await msg.delete()

    await edit_absence_main(
        state,
        trp("absence_files_attached_count").format(count=len(files)),
        kb=get_file_step_kb(data["file_mandatory"], len(files))
    )


@dp.callback_query(F.data == NEXT_FILE_STAGE, AbsenceFlow.DocumentUpload)
async def file_step_done(q: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("file_mandatory", True) and not data.get("files"):
        return await q.answer(trp("absence_mandatory_file_error"), show_alert=True)

    await state.set_state(AbsenceFlow.WaitingForComment)
    await edit_absence_main(
        state,
        trp("absence_write_comment"),
        kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=trp("btn_skip_comment"), callback_data=SKIP_COMMENT_CALLBACK)],
            [InlineKeyboardButton(text=trp("generic_back_button"), callback_data=BACK_CALLBACK)],
        ])
    )
    await q.answer()


async def _show_confirm_reason(state: FSMContext):
    data = await state.get_data()
    human_reason = {
        "illness": trp("reason_illness"),
        "family": trp("reason_family"),
        "vacation": trp("reason_vacation"),
        "other": f"{trp('reason_other')}: {data.get('other_text', '') or '—'}",
    }.get(data.get("reason_code"), "—")

    text = trp("absence_reason_filled").format(
        human_reason=human_reason,
        add_comment=data.get('add_comment') or '—'
    )
    await edit_absence_main(
        state, text,
        kb=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=trp("absence_btn_approve_reason"), callback_data=APPROVE_REASON_CALLBACK)],
            [InlineKeyboardButton(text=trp("absence_btn_edit_reason"), callback_data=EDIT_REASON_CALLBACK)],
        ])
    )
    await state.set_state(AbsenceFlow.ConfirmingReason)


@dp.message(AbsenceFlow.WaitingForComment, F.text)
async def handle_add_comment(msg: Message, state: FSMContext):
    await state.update_data(add_comment=msg.text.strip())
    await msg.delete()
    await _show_confirm_reason(state)


@dp.callback_query(F.data == SKIP_COMMENT_CALLBACK, AbsenceFlow.WaitingForComment)
async def handle_skip_comment(q: CallbackQuery, state: FSMContext):
    await state.update_data(add_comment=None)
    await _show_confirm_reason(state)
    await q.answer()


@dp.callback_query(F.data == APPROVE_REASON_CALLBACK, AbsenceFlow.ConfirmingReason)
async def approve_reason(q: CallbackQuery, state: FSMContext, dialog_manager: DialogManager):
    await dialog_manager.start(
        AbsenceCal.Start,
        mode=StartMode.RESET_STACK,
        data={"parent_fsm": state},
    )
    await q.answer()


@dp.callback_query(F.data == EDIT_REASON_CALLBACK, AbsenceFlow.ConfirmingReason)
async def edit_reason(q: CallbackQuery, state: FSMContext):
    await state.set_state(AbsenceFlow.ChoosingReason)
    await q.message.edit_text(
        trp("absence_choose_reason"),
        reply_markup=await get_reason_keyboard(selected=(await state.get_data()).get("reason_code"))
    )
    await q.answer()


@dp.callback_query(F.data == SUBMIT_CALLBACK, AbsenceFlow.ConfirmingDetails)
async def handle_final_submit(q: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    for mid in data.get("preview_msg_ids", []):
        try:
            await bot.delete_message(chat_id=q.message.chat.id, message_id=mid)
        except TelegramAPIError:
            pass

    absence_id_map = add_absences_for_locations(q.message.from_user.id, data)

    translated = ", ".join(
        LOCATION_NAMES.get(loc, loc) for loc in data.get("locations", [])
    )
    reason_human = {
        "illness": trp("reason_illness"),
        "family": trp("reason_family"),
        "vacation": trp("reason_vacation"),
        "other": f"{trp('reason_other')}: {data.get('other_text') or '—'}",
    }.get(data.get("reason_code"), "—")
    period = f'с {data["dates"]["start"]} по {data["dates"]["end"]}'
    card = get_user_card_data_by_id(user_id=q.from_user.id)
    full_name = card.get("full_name")
    text = (
        f"<b>Участница:</b> {full_name}\n"
        f"<b>Локация(ии):</b> {translated}\n"
        f"<b>Причина отсутствия:</b> {reason_human}\n"
        f"<b>Период:</b> {period}\n"
        f"<b>Комментарий:</b> {data.get('add_comment', '—')}"
    )

    for loc in data["locations"]:
        chat_id = absence_chat_map.get(loc)
        if not chat_id:
            continue

        abs_id = absence_id_map[loc]

        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=get_absence_admin_kb(abs_id),
            parse_mode="HTML",
        )

        photos: list[str] = []
        for ftype, file_id, filename in data.get("files", []):
            if ftype == "doc":
                await bot.send_document(
                    chat_id=chat_id,
                    document=file_id,
                    caption=filename or ""
                )
            else:
                photos.append(file_id)

        if photos:
            if len(photos) == 1:
                await bot.send_photo(chat_id=chat_id, photo=photos[0])
            else:
                media = [InputMediaPhoto(media=p) for p in photos]
                await bot.send_media_group(chat_id=chat_id, media=media)

    ids_str = ", ".join(map(str, absence_id_map.values()))
    await q.message.edit_text(
        trp("absence_card_sent_admin").format(ids_str=ids_str),
        reply_markup=back_to_menu_kb
    )
    await state.clear()
    await q.answer()


@dp.callback_query(F.data.startswith("absence_ok_"))
async def absence_approve(cb: CallbackQuery, state: FSMContext):
    abs_id = int(cb.data.split("_")[2])
    admin = cb.from_user
    approve_absence(abs_id, admin.id, "")
    info = get_absence_info(abs_id)
    place_ru = LOCATION_NAMES.get(info["place"], info["place"])
    await cb.message.edit_text(
        cb.message.text
        + "\n\n<b>Решение:</b> Согласовано\n"
        + f"<b>Принял решение:</b> {admin.mention_html()}",
        parse_mode="HTML"
    )
    await bot.send_message(
        chat_id=info["user_id"],
        text=trp("absence_notify_user_approved").format(
            place_ru=place_ru,
            date_from=info["date_from"],
            date_to=info["date_to"]
        ),
        parse_mode="HTML",
        reply_markup=delete_this_msg_kb
    )
    await cb.answer(trp("admin_event_approve_text"))


@dp.callback_query(F.data.startswith("absence_reject_"))
async def absence_reject_start(cb: CallbackQuery, state: FSMContext):
    abs_id = int(cb.data.split("_")[2])
    original_text = cb.message.text
    await state.update_data(
        absence_id=abs_id,
        request_chat_id=cb.message.chat.id,
        request_msg_id=cb.message.message_id,
        original_text=original_text
    )

    await cb.message.edit_reply_markup(reply_markup=None)

    prompt = await cb.message.answer(
        trp("absence_decision_add_comment_prompt"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=trp("logout_confirm_no"), callback_data="reject_back")]
        ])
    )
    await state.update_data(prompt_msg_id=prompt.message_id)
    await state.set_state(AdminAbsence.WaitingComment)
    await cb.answer()


@dp.message(AdminAbsence.WaitingComment)
async def absence_reject_comment(msg: Message, state: FSMContext):
    data = await state.get_data()
    abs_id: int = data["absence_id"]
    comment: str = msg.text.strip()
    admin = msg.from_user

    reject_absence(abs_id, admin.id, comment)

    info = get_absence_info(abs_id)
    place_ru = LOCATION_NAMES.get(info["place"], info["place"])

    await bot.edit_message_text(
        chat_id=data["request_chat_id"],
        message_id=data["request_msg_id"],
        text=(
            f"{data['original_text']}\n\n"
            f"<b>Решение:</b> Отклонено\n"
            f"<b>Принял решение:</b> {admin.mention_html()}\n"
            f"<b>Комментарий:</b> {comment}"
        ),
        parse_mode="HTML",
    )

    await bot.send_message(
        chat_id=info["user_id"],
        text=trp("absence_notify_user_rejected").format(
            place_ru=place_ru,
            date_from=info["date_from"],
            date_to=info["date_to"],
            comment=comment
        ),
        parse_mode="HTML",
        reply_markup=delete_this_msg_kb,
    )

    await bot.delete_message(
        chat_id=data["request_chat_id"],
        message_id=data["prompt_msg_id"],
    )

    await state.clear()


@dp.callback_query(F.data == BACK_CALLBACK, StateFilter(AbsenceFlow))
async def absence_back(q: CallbackQuery, state: FSMContext):
    cur = await state.get_state()
    data = await state.get_data()

    if cur == AbsenceFlow.ConfirmingDetails.state:
        for mid in data.get("preview_msg_ids", []):
            try:
                await bot.delete_message(chat_id=q.message.chat.id, message_id=mid)
            except TelegramAPIError:
                pass
        data["preview_msg_ids"] = []
        await state.update_data(preview_msg_ids=[])

    mapping = {
        AbsenceFlow.ConfirmingDetails.state: AbsenceFlow.WaitingForComment,
        AbsenceFlow.WaitingForComment.state: AbsenceFlow.DocumentUpload,
        AbsenceFlow.DocumentUpload.state: AbsenceFlow.WaitingForOther
        if data.get("reason_code") == "other"
        else AbsenceFlow.ChoosingReason,
        AbsenceFlow.WaitingForOther.state: AbsenceFlow.ChoosingReason,
        AbsenceFlow.ChoosingReason.state: AbsenceFlow.ChoosingLocation,
    }
    prev = mapping.get(cur)
    if not prev:
        return await q.answer()

    await state.set_state(prev)

    if prev == AbsenceFlow.ChoosingLocation:
        await edit_absence_main(
            state,
            trp("absence_choose_location"),
            kb=await get_location_keyboard(selected=data.get("locations", []))
        )
    elif prev == AbsenceFlow.ChoosingReason:
        await edit_absence_main(
            state,
            trp("absence_choose_reason"),
            kb=await get_reason_keyboard(selected=data.get("reason_code"))
        )
    elif prev == AbsenceFlow.WaitingForOther:
        await edit_absence_main(
            state,
            trp("absence_prompt_other_reason"),
            kb=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=trp("generic_back_button"), callback_data=BACK_CALLBACK)]
            ])
        )
    elif prev == AbsenceFlow.DocumentUpload:
        await start_file_step(
            state,
            code=data.get("reason_code"),
            mandatory=data.get("file_mandatory", True)
        )
    elif prev == AbsenceFlow.WaitingForComment:
        await edit_absence_main(
            state,
            trp("absence_write_comment"),
            kb=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=trp("btn_skip_comment"), callback_data=SKIP_COMMENT_CALLBACK)],
                [InlineKeyboardButton(text=trp("generic_back_button"), callback_data=BACK_CALLBACK)],
            ])
        )
    await q.answer(trp("btn_back_to_menu"))


@dp.callback_query(F.data == "delete_this_msg")
async def delete_this_msg_h(callback_query: CallbackQuery):
    await callback_query.message.delete()


@dp.callback_query(F.data == "user_main_menu")
async def user_main_menu(callback_query: CallbackQuery, state: FSMContext):
    await state.set_state()
    try:
        await callback_query.message.edit_text(
            trp("welcome_root"),
            reply_markup=user_main_menu_kb
        )
    except TelegramBadRequest:
        await callback_query.message.answer(
            trp("welcome_root"),
            reply_markup=user_main_menu_kb
        )
        await callback_query.message.delete()
    await callback_query.answer()
