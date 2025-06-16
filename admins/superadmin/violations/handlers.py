"""
handlers_commented.py  — основной набор хендлеров (aiogram) для сценария
фиксации административных нарушений участниц.

В файле реализованы все шаги процесса:
    1. Поиск участницы через inline‑режим               (VioFSM.FindUser)
    2. Показ карточки + выбор цикла (если есть)         (CardShort / CardFull)
    3. Выбор тяжести нарушения                          (ChooseSeverity)
    4. Выбор типового шаблона или ручной ввод описания  (ChooseTemplate / CustomDescr)
    5. Выбор даты нарушения                             (ChooseDate)
    6. Загрузка файла‑подтверждения                     (WaitingFile)
    7. Подтверждение данных                             (Confirm)
    8. Запись результата в БД + сохранение файла        (vio_save)

Структура
---------
Файл поделен на тематические блоки, каждый начинается с
комментария вида «───────────── … ─────────────».

Важно:
    • Все callback‑данные имеют префикс `vio_`, что облегчает маршрутизацию.
    • Каждое состояние FSM чётко обозначено в декораторах aiogram.
    • Старайтесь избегать дублирования текста сообщений: для редактирования
      используем id ранее сохранённого сообщения (`gmsgid` в FSM‑данных).

Советы по доработке
-------------------
    • При добавлении новых тяжестей нарушений обновите `SEV_RU` и шаблоны
      в Excel‑файле `violations.xlsx`.
    • Чтобы хранить файлы локально, вместо file_id можно скачать файл через
      `bot.get_file` + `bot.download_file`. В таком случае колонку
      `file_path` в таблице `user_documents` нужно трактовать как путь.

Ниже приведён оригинальный код без изменений, чтобы сохранить работоспособность.
Дополнительные комментарии добавлены прямо в коде (поиск по «# 🗯️»).
"""

from aiogram import F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from datetime import datetime

from aiogram.types import InputTextMessageContent, InlineQueryResultArticle, InputMediaPhoto
from aiogram_dialog import DialogManager, StartMode

from admins.filters.is_admin import IsAdmin
from admins.superadmin.violations.states import VioFSM, ViolCal
from admins.superadmin.violations.keyboards import *
from admins.utils import build_admin_card_text
from db.database import cursor, conn, search_users_by_fio, get_participant_card, get_photo_or_none
from config import dp, bot

SEV_RU = {"light": "Лёгкое", "medium": "Среднее", "heavy": "Тяжёлое"}


# ───────────── поиск участницы ─────────────
def _normalize(text: str) -> str:
    import re
    text = re.sub(r"\s+", " ", text.strip())
    return "%" + "%".join(text.split(" ")) + "%"


@dp.callback_query(F.data == "sa_violations", IsAdmin())
async def vio_entry(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(VioFSM.FindUser)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Найти участницу",
                                  switch_inline_query_current_chat="vu: ")],
            [InlineKeyboardButton(text="Назад", callback_data="a_menu")]
        ]
    )
    # ‼️ сохраняем ID сообщения, которое будем потом редактировать
    await state.update_data(gmsgid=cb.message.message_id)

    await cb.message.edit_text("Нажмите «🔍 Найти участницу» и начните вводить ФИО/username/роль:",
                               reply_markup=kb)
    await cb.answer()


@dp.inline_query(VioFSM.FindUser, IsAdmin())
async def vio_inline_search(query: types.InlineQuery, state: FSMContext):
    text = query.query.strip()
    if text.lower().startswith("vu:"):
        text = text[3:].lstrip()

    if len(text) < 2:
        return await query.answer([], cache_time=1)

    users = search_users_by_fio(text, 25)
    results = [
        InlineQueryResultArticle(
            id=str(u.get("id")),
            title=u.get("full_name"),
            description=f"Тик: {u.get("tik") or '—'}",
            input_message_content=InputTextMessageContent(
                message_text=f"#VU{u.get("id")}"
            )
        )
        for u in users
    ]
    await query.answer(results, cache_time=1)


# ───────────── выбран #VU<ID> ─────────────
@dp.message(VioFSM.FindUser, F.text.startswith("#VU"), IsAdmin())
async def vio_user_selected(msg: types.Message, state: FSMContext):
    try:
        uid = int(msg.text[3:])
    except ValueError:
        return

    # выбираем все доступные циклы
    cursor.execute("""
        SELECT full_name, username
          FROM users
         WHERE user_id = ?
    """, (uid,))
    row = cursor.fetchone()
    if not row:
        await msg.reply("❗️ Участница не найдена.")
        return
    card = get_participant_card(uid)
    caption = build_admin_card_text(card)
    kb = main_card_kb(uid)
    photo = get_photo_or_none(card)
    data = await state.get_data()

    if photo:  # ---------- фото есть ----------
        try:
            await bot.edit_message_media(
                chat_id=msg.chat.id,
                message_id=data.get("gmsgid"),
                media=InputMediaPhoto(media=photo, caption=caption, parse_mode="HTML"),
                reply_markup=kb
            )
        except Exception:
            # если старое сообщение было без фото → отправляем новое
            await msg.delete()
            await msg.answer_photo(photo, caption=caption,
                                   parse_mode="HTML", reply_markup=kb)
    else:  # ---------- фото нет ----------
        await bot.edit_message_text(chat_id=msg.chat.id,
                                    message_id=data.get("gmsgid"),
                                    text=caption, parse_mode="HTML", reply_markup=kb)

    await state.set_state(VioFSM.CardFull)
    await msg.delete()


# ───────────── выбор серьёзности ─────────────
@dp.callback_query(F.data.startswith("vio_start:"), IsAdmin())
async def vio_start(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(VioFSM.ChooseSeverity)
    try:
        await cb.message.edit_text("Выберите тяжесть нарушения:", reply_markup=severity_kb())
    except TelegramBadRequest:
        await cb.message.answer("Выберите тяжесть нарушения:", reply_markup=severity_kb())
        await cb.message.delete()
    await cb.answer()


@dp.callback_query(VioFSM.ChooseSeverity, F.data.startswith("vio_s:"), IsAdmin())
async def vio_choose_sev(cb: types.CallbackQuery, state: FSMContext):
    _, sev = cb.data.split(":")
    await state.update_data(sev=sev)
    await state.set_state(VioFSM.ChooseTemplate)
    await cb.message.edit_text("Выберите типовой шаблон:", reply_markup=template_kb(sev))
    await cb.answer()


# ───────────── шаблон / другое ─────────────
@dp.callback_query(VioFSM.ChooseTemplate, F.data.startswith("vio_tpl_idx:"), IsAdmin())
async def vio_tpl_selected(cb: types.CallbackQuery, state: FSMContext):
    idx_str = cb.data.split(":")[1]
    if idx_str == "custom":
        await state.set_state(VioFSM.CustomDescr)
        await cb.message.edit_text("Опишите нарушение кратко:",
                                   reply_markup=InlineKeyboardMarkup(
                                       inline_keyboard=[[InlineKeyboardButton(text="Назад",
                                                                              callback_data="vio_back2tpl")]]
                                   ))
    else:
        idx = int(idx_str)
        sev = (await state.get_data())["sev"]
        df = pd.read_excel(XL_PATH)
        descr = df[sev].dropna().iloc[idx]  # ← исправлено
        await state.update_data(descr=descr)
        await _ask_date(cb, state)
    await cb.answer()


@dp.message(VioFSM.CustomDescr, IsAdmin())
async def vio_save_descr(msg: types.Message, state: FSMContext):
    await state.update_data(descr=msg.text.strip())
    await _ask_date(msg, state)
    await bot.delete_message(msg.chat.id, msg.message_id - 1)
    await msg.delete()


async def _ask_date(evmsg: types.Union[types.CallbackQuery, types.Message],
                    state: FSMContext) -> None:
    """
    Показываем шаг выбора даты:
      • если пришёл CallbackQuery → редактируем то же сообщение;
      • если обычный Message       → отправляем новое сообщение.
    """
    await state.set_state(VioFSM.ChooseDate)

    text = "Выберите дату нарушения:"
    kb = date_kb()

    if isinstance(evmsg, types.CallbackQuery):
        await evmsg.message.edit_text(text, reply_markup=kb)
        await state.update_data(gmsgid=evmsg.message.message_id)
    else:  # Message
        msg = await evmsg.answer(text, reply_markup=kb)
        await state.update_data(gmsgid=msg.message_id)


async def _ask_file(evmsg: types.Union[types.CallbackQuery, types.Message], state: FSMContext):
    await state.set_state(VioFSM.WaitingFile)
    text = "📎 Прикрепите фото или документ-подтверждение нарушения."
    kb = attach_back_kb()
    if isinstance(evmsg, types.CallbackQuery):
        await evmsg.message.edit_text(text, reply_markup=kb)
        await state.update_data(gmsgid=evmsg.message.message_id)
    else:  # Message
        msg = await evmsg.answer(text, reply_markup=kb)
        await state.update_data(gmsgid=msg.message_id)


@dp.callback_query(VioFSM.ChooseDate, F.data == "vio_date:cal", IsAdmin())
async def vio_date_calendar(cb: types.CallbackQuery,
                            state: FSMContext,
                            dialog_manager: DialogManager):
    """
    Открываем календарь. После выбора даты _confirm() вызывается из on_pick().
    """
    await dialog_manager.start(
        ViolCal.Pick,
        mode=StartMode.RESET_STACK,
        data={"parent_fsm": state}
    )
    await cb.answer()


@dp.callback_query(VioFSM.ChooseDate, F.data.startswith("vio_date:"), IsAdmin())
async def vio_date_quick(cb: types.CallbackQuery, state: FSMContext):
    if cb.data.endswith(":today"):
        date_str = datetime.now().strftime("%d.%m.%Y")
        await state.update_data(vdate=date_str)
        await _ask_file(cb, state)
    await cb.answer()


@dp.message(VioFSM.WaitingFile, F.document | F.photo, IsAdmin())
async def vio_got_file(msg: types.Message, state: FSMContext):
    file_id = msg.document.file_id if msg.document else msg.photo[-1].file_id
    await state.update_data(attach=file_id,
                            attach_type="document" if msg.document else "photo")
    await _confirm_with_media(msg, state)
    try:
        await bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id - 1)
    except TelegramBadRequest:
        pass
    await msg.delete()


async def _confirm_with_media(evmsg, state: FSMContext):
    d = await state.get_data()

    # ФИО + username
    cursor.execute("SELECT full_name, username FROM users WHERE user_id=?", (d["uid"],))
    full_name, username = cursor.fetchone()
    uname_part = f" (@{username})" if username else ""

    caption = (f"Проверьте данные:\n\n"
               f"👤 <b>{full_name}</b>{uname_part}\n"
               f"ID: <code>{d['uid']}</code>\n"
               f"Тяжесть: <b>{SEV_RU[d['sev']]}</b>\n"
               f"Описание: {d['descr']}\n"
               f"Дата: {d['vdate']}")

    await state.set_state(VioFSM.Confirm)

    if d["attach_type"] == "photo":
        await evmsg.answer_photo(
            d["attach"], caption=caption, parse_mode="HTML", reply_markup=confirm_kb()
        )
    else:
        await evmsg.answer_document(
            d["attach"], caption=caption, parse_mode="HTML", reply_markup=confirm_kb()
        )


# ───────────── сохранение в БД ─────────────
@dp.callback_query(VioFSM.Confirm, F.data == "vio_save", IsAdmin())
async def vio_save(cb: types.CallbackQuery, state: FSMContext):
    d = await state.get_data()
    # 1. запись в violations
    cursor.execute("""
        INSERT INTO violations (user_id, admin_id, description,
                                violation_date, severity)
        VALUES (?, ?, ?, ?, ?)
    """, (d["uid"], cb.from_user.id, d["descr"],
          datetime.strptime(d["vdate"], "%d.%m.%Y").strftime("%Y-%m-%d"),
          d["sev"]))
    vio_id = cursor.lastrowid
    # 2. сохраняем файл-доказательство
    cursor.execute("""
        INSERT INTO user_documents (user_id, document_type, file_path, comment, status)
        VALUES (?, 'violation_proof', ?, ?, 'accepted')
    """, (d["uid"], d["attach"], f"violation:{vio_id}"))
    conn.commit()
    from admins.keyboards import get_superadmin_panel_kb
    await cb.message.answer("✅ Нарушение успешно зафиксировано!", reply_markup=get_superadmin_panel_kb())
    await cb.message.delete()
    await state.clear()


# ───────────── «Назад» хендлеры (упрощённо) ─────────────
@dp.callback_query(F.data.startswith("vio_back"), IsAdmin())
async def vio_back(cb: types.CallbackQuery, state: FSMContext):
    # для краткости: всегда возвращаемся в главное меню суперадмина
    from admins.keyboards import get_superadmin_panel_kb
    await state.clear()
    await cb.message.edit_text("Панель суперадмина:", reply_markup=get_superadmin_panel_kb())
    await cb.answer()
