"""
Хэндлеры для роли «администратор» (admin).

Функциональность:
1. Просмотр FAQ с пагинацией.
2. Задать вопрос суперадминам и получить ответ.
3. Поиск участницы по ФИО через inline-query и вывод карточки.
"""

from __future__ import annotations

import asyncio
from typing import Final, Optional

from aiogram import F, html, types
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
)
from aiogram.fsm.context import FSMContext
from aiogram.types import InputMediaPhoto, InputTextMessageContent, InlineQueryResultArticle
from aiogram.utils.keyboard import InlineKeyboardBuilder

from admins.admin.keyboards import (
    build_faq_page_kb,
    back_to_menu_a_kb,
    get_sa_reply_kb,
)
from admins.admin.states import AskSAForm, SAReplyForm, AParticipantSearch
from admins.filters.is_admin import IsAdmin
from admins.keyboards import get_admin_panel_kb
from admins.utils import build_admin_card_text
from config import (
    dp,
    bot,
    report_questions_from_admins_chat_id,
    ROLES,
)
from db.database import (
    get_participant_card,
    get_photo_or_none,
    get_user_role,
    load_faq_from_db,
    search_users_by_fio,
)
from user.auth.keyboards import delete_this_msg_kb

# --------------------------------------------------------------------------- #
#                            1. Главное меню                                  #
# --------------------------------------------------------------------------- #


@dp.callback_query(F.data == "a_menu", IsAdmin())
async def back_to_admin_menu(cb: types.CallbackQuery) -> None:
    """Возврат к корневому меню администратора."""
    await cb.message.edit_text("Панель админа", reply_markup=get_admin_panel_kb())
    await cb.answer()


# --------------------------------------------------------------------------- #
#                               2. FAQ                                        #
# --------------------------------------------------------------------------- #

_FAQ_EMPTY_MSG: Final = "FAQ пустой"


@dp.callback_query(F.data == "a_faq", IsAdmin())
async def open_faq(cb: types.CallbackQuery) -> None:
    """Показываем первую страницу FAQ."""
    faq_data = load_faq_from_db(cb.from_user.id)
    if not faq_data:
        return await cb.answer(_FAQ_EMPTY_MSG, show_alert=True)

    kb = build_faq_page_kb(faq_data, page=0)
    await cb.message.edit_text(
        "Выберите вопрос, на который хотите получить ответ:",
        reply_markup=kb,
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("afaq_page:"), IsAdmin())
async def paginate_faq(cb: types.CallbackQuery) -> None:
    """Переключение страниц FAQ (◀️ 1/10 ▶️)."""
    faq_data = load_faq_from_db(cb.from_user.id)
    if not faq_data:
        return await cb.answer(_FAQ_EMPTY_MSG, show_alert=True)

    page: int = int(cb.data.split(":")[1])
    kb = build_faq_page_kb(faq_data, page)
    await cb.message.edit_reply_markup(reply_markup=kb)
    await cb.answer()


@dp.callback_query(F.data.startswith("afaq_q:"), IsAdmin())
async def show_answer(cb: types.CallbackQuery) -> None:
    """
    Показ ответа на выбранный вопрос.

    callback-data формата: "afaq_q:{q_id}:{page}"
    """
    _, q_id_str, page_str = cb.data.split(":")
    q_id: int = int(q_id_str)
    page: int = int(page_str)

    faq_data = load_faq_from_db(cb.from_user.id)
    answer_item = next((i for i in faq_data if i["id"] == q_id), None)
    if not answer_item:
        return await cb.answer("Вопрос не найден", show_alert=True)

    text = f"<b>{answer_item['question']}</b>\n\n{answer_item['answer']}"

    kb = InlineKeyboardBuilder()
    kb.button(text="Вернуться к FAQ", callback_data=f"afaq_page:{page}")
    kb.button(text="Вернуться в меню", callback_data="a_menu")
    await cb.message.edit_text(text, reply_markup=kb.adjust(1).as_markup(), parse_mode="HTML")
    await cb.answer()


# --------------------------------------------------------------------------- #
#                 3. «Задать вопрос суперадминам»                             #
# --------------------------------------------------------------------------- #


@dp.callback_query(F.data == "a_ask", IsAdmin())
async def ask_sa_start(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Начинаем FSM: админ вводит вопрос."""
    await state.set_state(AskSAForm.WaitingForQuestion)
    await state.update_data(main_msg_id=cb.message.message_id)

    await cb.message.edit_text(
        "Напишите ваш вопрос для суперадминов:",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text="🚫 Отмена", callback_data="a_cancel_q")]]
        ),
    )
    await cb.answer()


@dp.callback_query(F.data == "a_cancel_q", AskSAForm.WaitingForQuestion, IsAdmin())
async def ask_sa_cancel(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Отмена ввода вопроса."""
    await state.clear()
    await cb.message.edit_text("Отправка вопроса отменена.", reply_markup=get_admin_panel_kb())
    await cb.answer()


@dp.message(AskSAForm.WaitingForQuestion, IsAdmin())
async def process_sa_question(msg: types.Message, state: FSMContext) -> None:
    """Получаем текст вопроса администратора и отправляем его в группу СА."""
    await state.clear()

    admin = msg.from_user
    q_text: str = msg.text or ""

    admin_info = html.quote(admin.full_name)
    if admin.username:
        admin_info += f" (@{admin.username})"
    admin_info += f"\nID: {admin.id}"

    role_code = get_user_role(admin.id)
    role_text = ROLES.get(role_code, role_code)

    header = f"❓ <b>Вопрос от «{role_text}»</b>\n\n{admin_info}\n\n"
    base_text = f"{header}<b>Вопрос:</b>\n{html.quote(q_text)}"

    # ▸ пробуем переслать оригинал, чтобы сохранить контекст
    extra = ""
    try:
        await bot.forward_message(
            chat_id=report_questions_from_admins_chat_id,
            from_chat_id=msg.chat.id,
            message_id=msg.message_id,
        )
    except TelegramForbiddenError:
        extra = "\n\n⚠️ <i>Не удалось переслать оригинал (админ запретил пересылку).</i>"
    except Exception as exc:  # pylint: disable=broad-except
        extra = f"\n\n❗️ <i>Ошибка при пересылке: {exc}</i>"

    await bot.send_message(
        chat_id=report_questions_from_admins_chat_id,
        text=base_text + extra,
        parse_mode="HTML",
        reply_markup=get_sa_reply_kb(admin.id),
    )

    # ▸ уведомляем администратора
    data = await state.get_data()
    main_msg_id: Optional[int] = data.get("main_msg_id")
    if main_msg_id:
        await bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=main_msg_id,
            text="Спасибо! Вопрос отправлен суперадминам. Ожидайте ответа.",
            reply_markup=get_admin_panel_kb(),
        )


# ─────────────── ответ СА на вопрос администратора ──────────────── #


@dp.callback_query(F.data.startswith("sa_reply_"), IsAdmin())
async def sa_start_reply(cb: types.CallbackQuery, state: FSMContext) -> None:
    """
    Суперадмин нажал «✉️ Ответить» под вопросом → начинаем FSM.

    callback-data: "sa_reply_{admin_id}"
    """
    sa_user = cb.from_user
    admin_id: int = int(cb.data.split("_")[2])

    await state.set_state(SAReplyForm.WaitingForReplyText)
    await state.update_data(
        target_admin_id=admin_id,
        group_msg_id=cb.message.message_id,
        original_text=cb.message.text,
    )

    sa_info = html.quote(sa_user.full_name)
    if sa_user.username:
        sa_info += f" (@{sa_user.username})"

    await cb.message.edit_text(
        f"{cb.message.text}\n\n⏳ <b>{sa_info}</b> пишет ответ...",
        parse_mode="HTML",
    )
    await cb.answer("Введите ответ для администратора в этот чат.")


@dp.message(SAReplyForm.WaitingForReplyText, IsAdmin())
async def sa_process_reply(msg: types.Message, state: FSMContext) -> None:
    """Принимаем ответ суперадмина и пересылаем админу."""
    if msg.chat.id != report_questions_from_admins_chat_id:
        # принимаем ответы ТОЛЬКО из группы суперадминов
        return

    data = await state.get_data()
    admin_id: int = data["target_admin_id"]
    group_msg_id: int = data["group_msg_id"]
    original_text: str = data["original_text"]

    sa = msg.from_user
    answer: str = msg.text or ""

    # 1) отправляем админу
    try:
        await bot.send_message(
            chat_id=admin_id,
            text=f"✉️ Ответ от суперадмина ({html.quote(sa.full_name)}):\n\n"
            f"{html.quote(answer)}",
            parse_mode="HTML",
            reply_markup=delete_this_msg_kb,
        )
        delivered = True
    except TelegramForbiddenError:
        delivered = False

    # 2) редактируем сообщение в группе
    sa_info = html.quote(sa.full_name)
    if sa.username:
        sa_info += f" (@{sa.username})"

    final_text = (
        f"{original_text}\n\n"
        f"✅ <b>Ответ отправлен:</b>\n{html.quote(answer)}\n\n"
        f"👤 <b>Ответил:</b> {sa_info}"
    )
    if not delivered:
        final_text += (
            "\n\n<tg-spoiler>"
            "⚠️ Администратор не получил ответ (возможно, закрыл ЛС)."
            "</tg-spoiler>"
        )

    await bot.edit_message_text(
        chat_id=report_questions_from_admins_chat_id,
        message_id=group_msg_id,
        text=final_text,
        parse_mode="HTML",
    )

    await state.clear()


# --------------------------------------------------------------------------- #
#                        4. Поиск участницы по ФИО                            #
# --------------------------------------------------------------------------- #


@dp.callback_query(F.data == "a_participants", IsAdmin())
async def start_fio_search(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Выводим кнопку «🔍 Найти участницу» и переходим в режим inline-поиска."""
    await state.set_state(AParticipantSearch.WaitingInline)
    await state.update_data(prompt_msg_id=cb.message.message_id)

    kb = InlineKeyboardBuilder()
    kb.button(text="🔍 Найти участницу", switch_inline_query_current_chat="fio: ")
    kb.button(text="🔙 В меню", callback_data="a_menu")

    await cb.message.edit_text(
        "Нажмите «Найти участницу» и начните вводить ФИО.\n"
        "Выберите нужную из выпадающего списка.",
        reply_markup=kb.adjust(1).as_markup(),
        parse_mode="HTML",
    )
    await cb.answer()


@dp.message(AParticipantSearch.WaitingInline, F.text.startswith("#UID"), IsAdmin())
async def handle_uid_message(msg: types.Message, state: FSMContext) -> None:
    """Админ прислал «#UID123» → показываем карточку участницы + фото."""
    try:
        user_id: int = int(msg.text[4:])
    except ValueError:
        return  # некорректный формат — игнорируем

    data = await state.get_data()
    prompt_id: Optional[int] = data.get("prompt_msg_id")

    # 1) карточка участницы
    card = get_participant_card(user_id)
    if not card:
        return await msg.answer("❗️ Не удалось загрузить данные участницы")

    caption: str = build_admin_card_text(card)

    # 2) клавиатура
    kb = InlineKeyboardBuilder()
    kb.row(
        types.InlineKeyboardButton(text="🔙 Назад", callback_data="a_participants"),
        types.InlineKeyboardButton(text="🏠 В меню", callback_data="a_menu"),
    )
    reply_markup = kb.as_markup()

    # 3) фото (file_id | FSInputFile | None)
    photo_obj = get_photo_or_none(card)

    # 4) редактируем «старое» сообщение или шлём новое
    try:
        if prompt_id and photo_obj:
            await bot.edit_message_media(
                chat_id=msg.chat.id,
                message_id=prompt_id,
                media=InputMediaPhoto(
                    media=photo_obj, caption=caption, parse_mode="HTML"
                ),
                reply_markup=reply_markup,
            )
        elif prompt_id:
            await bot.edit_message_text(
                chat_id=msg.chat.id,
                message_id=prompt_id,
                text=caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        else:
            raise TelegramBadRequest  # заставляем перейти в except
    except TelegramBadRequest:
        # если исходное сообщение нельзя изменить (или prompt_id нет)
        if photo_obj:
            await bot.send_photo(
                chat_id=msg.chat.id,
                photo=photo_obj,
                caption=caption,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        else:
            await msg.answer(caption, parse_mode="HTML", reply_markup=reply_markup)
    except TelegramAPIError as exc:
        # любая другая ошибка TG
        print(f"[admin UID handler] telegram error: {exc}")
        await msg.answer(caption, parse_mode="HTML", reply_markup=reply_markup)

    # 5) удаляем «#UID…» сообщение-метку
    with contextlib.suppress(TelegramAPIError):
        await msg.delete()


# ───────────────── inline-query поиск ФИО ─────────────────


@dp.inline_query(AParticipantSearch.WaitingInline, IsAdmin())
async def inline_fio(query: types.InlineQuery) -> None:
    text: str = query.query.lstrip()

    # убираем префикс "fio:" (регистр не важен)
    if text.lower().startswith("fio:"):
        text = text[4:].lstrip()

    if len(text) < 2:
        return await query.answer([], cache_time=1)

    users = search_users_by_fio(text, limit=25)
    if not users:
        return await query.answer(
            [],
            cache_time=1,
            switch_pm_text="Не найдено",
            switch_pm_parameter="fio_not_found",
        )

    results: list[InlineQueryResultArticle] = [
        InlineQueryResultArticle(
            id=str(u["id"]),
            title=u["full_name"],
            description=f"Тик: {u['tik']}",
            input_message_content=InputTextMessageContent(message_text=f"#UID{u['id']}"),
        )
        for u in users
    ]
    await query.answer(results, cache_time=1)


# --------------------------------------------------------------------------- #
#                   5. Полная карточка по циклу (ucard)                       #
# --------------------------------------------------------------------------- #


@dp.callback_query(F.data.startswith("ucard:"), IsAdmin())
async def show_cycle_card(cb: types.CallbackQuery) -> None:
    """
    Показ полной карточки участницы (в том числе из inline-режима).

    callback-data: "ucard:{uid}:{cycle}"
    """
    _, uid_str, cycle_str = cb.data.split(":")  # cycle пока не используем
    uid: int = int(uid_str)

    card = get_participant_card(uid)
    if not card:
        return await cb.answer("Не удалось загрузить карту участницы", show_alert=True)

    caption = build_admin_card_text(card)
    photo_id = get_photo_or_none(card)

    kb = back_to_menu_a_kb()

    try:
        if photo_id:
            if cb.message:  # обычный чат
                await cb.message.answer_photo(
                    photo=photo_id, caption=caption, parse_mode="HTML", reply_markup=kb
                )
            else:  # inline-сообщение
                await cb.bot.edit_message_media(
                    inline_message_id=cb.inline_message_id,
                    media=types.InputMediaPhoto(
                        media=photo_id, caption=caption, parse_mode="HTML"
                    ),
                    reply_markup=kb,
                )
        else:
            if cb.message:
                await cb.message.edit_text(caption, parse_mode="HTML", reply_markup=kb)
            else:
                await cb.bot.edit_message_text(
                    inline_message_id=cb.inline_message_id,
                    text=caption,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
    except TelegramBadRequest:
        # запасной вариант — новое сообщение
        await cb.message.answer(caption, parse_mode="HTML", reply_markup=kb)

    await cb.answer()
