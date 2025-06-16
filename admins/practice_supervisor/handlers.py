"""
Handlers for the «Practice Supervisor» role
===========================================

Функциональность
----------------
1. Просмотр FAQ с пагинацией.
2. Отправка вопроса суперадминам.
3. Поиск участницы (inline) и просмотр карточки.
4. Сбор обратной связи по практике (ЗКА, ЗКО, SMART-feedback, пропуски).
"""

from __future__ import annotations

import contextlib
from html import escape
from typing import Final, Optional

from aiogram import F, html, types
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputTextMessageContent,
    InlineQueryResultArticle,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from admins.admin.keyboards import get_sa_reply_kb
from admins.admin.states import AskSAForm
from admins.filters.is_admin import IsAdmin
from admins.keyboards import get_practice_supervisor_panel_kb
from admins.practice_supervisor.keyboards import (
    _build_faq_page_kb,
    back_menu_p_kb,
    back_from_fb_kb,
    back_to_menu_p_kb,
    absence_kb,
    scale_kb,
)
from admins.practice_supervisor.states import PSParticipantSearch, PracticeFeedback
from admins.utils import build_admin_card_text
from config import bot, dp, report_questions_from_admins_chat_id, feedback_chat_id
from db.database import (
    load_faq_from_db,
    get_participant_card,
    get_photo_or_none,
    search_users_by_fio,
    save_practice_feedback,
    get_bool_setting,
)

# --------------------------------------------------------------------------- #
#                               1. Главное меню                               #
# --------------------------------------------------------------------------- #


@dp.callback_query(F.data == "p_menu", IsAdmin())
async def ps_back_to_menu(cb: CallbackQuery) -> None:
    """Возврат к корневому меню РП."""
    await cb.message.edit_text(
        "Панель руководителя практики",
        reply_markup=get_practice_supervisor_panel_kb(),
    )
    await cb.answer()


# --------------------------------------------------------------------------- #
#                                    FAQ                                      #
# --------------------------------------------------------------------------- #

_FAQ_EMPTY_MSG: Final = "FAQ пустой"


@dp.callback_query(F.data == "p_faq", IsAdmin())
async def ps_open_faq(cb: CallbackQuery) -> None:
    """Открываем первую страницу FAQ."""
    faq = load_faq_from_db(cb.from_user.id)
    if not faq:
        return await cb.answer(_FAQ_EMPTY_MSG, show_alert=True)

    await cb.message.edit_text(
        "Выберите вопрос:",
        reply_markup=_build_faq_page_kb(faq, 0),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("pfaq_page:"), IsAdmin())
async def ps_paginate_faq(cb: CallbackQuery) -> None:
    """Переключение страниц FAQ."""
    faq = load_faq_from_db(cb.from_user.id)
    page: int = int(cb.data.split(":")[1])
    await cb.message.edit_reply_markup(reply_markup=_build_faq_page_kb(faq, page))
    await cb.answer()


@dp.callback_query(F.data.startswith("pfaq_q:"), IsAdmin())
async def ps_show_answer(cb: CallbackQuery) -> None:
    """
    Показ ответа на вопрос.

    callback-data: ``pfaq_q:{q_id}:{page}``
    """
    _, q_id_str, page_str = cb.data.split(":")
    q_id, page = int(q_id_str), int(page_str)

    faq = load_faq_from_db(cb.from_user.id)
    item = next((i for i in faq if i["id"] == q_id), None)
    if not item:
        return await cb.answer("Вопрос не найден", show_alert=True)

    text = f"<b>{item['question']}</b>\n\n{item['answer']}"

    try:
        await cb.message.edit_text(
            text=text,
            reply_markup=_build_faq_page_kb(faq, page),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        # если исходное сообщение нельзя изменить (например, слишком много текста)
        await cb.message.delete()
        await cb.message.answer(
            text=text,
            reply_markup=_build_faq_page_kb(faq, page),
            parse_mode="HTML",
        )
    await cb.answer()


# --------------------------------------------------------------------------- #
#                    2. «Задать вопрос суперадминам»                          #
# --------------------------------------------------------------------------- #


@dp.callback_query(F.data == "p_ask", IsAdmin())
async def ps_ask_start(cb: CallbackQuery, state: FSMContext) -> None:
    """Запрашиваем у РП текст вопроса для суперадминов."""
    await state.set_state(AskSAForm.WaitingForQuestion)
    await state.update_data(main_msg_id=cb.message.message_id, role_label="Руководитель практики")

    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🚫 Отмена", callback_data="p_q_cancel")]]
    )
    await cb.message.edit_text("Напишите ваш вопрос для суперадминов:", reply_markup=cancel_kb)
    await cb.answer()


@dp.callback_query(F.data == "p_q_cancel", AskSAForm.WaitingForQuestion, IsAdmin())
async def ps_q_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    """Отмена ввода вопроса."""
    await state.clear()
    await cb.message.edit_text("Отправка вопроса отменена.", reply_markup=get_practice_supervisor_panel_kb())
    await cb.answer()


@dp.message(AskSAForm.WaitingForQuestion, IsAdmin())
async def ps_process_question(msg: Message, state: FSMContext) -> None:
    """Получаем текст вопроса и отправляем его в группу суперадминов."""
    data = await state.get_data()
    role_label: str = data.get("role_label", "Руководитель практики")

    q_text: str = msg.text or ""
    user = msg.from_user

    header = (
        f"❓ <b>Вопрос от «{role_label}»</b>\n\n"
        f"{html.quote(user.full_name)}"
        f"{f' (@{user.username})' if user.username else ''}\n"
        f"ID: {user.id}\n\n"
        f"<b>Вопрос:</b>\n{html.quote(q_text)}"
    )

    await bot.send_message(
        chat_id=report_questions_from_admins_chat_id,
        text=header,
        parse_mode="HTML",
        reply_markup=get_sa_reply_kb(user.id),
    )

    ref: Optional[int] = data.get("main_msg_id")
    if ref:
        await bot.edit_message_text(
            "Спасибо! Вопрос отправлен суперадминам.",
            chat_id=msg.chat.id,
            message_id=ref,
            reply_markup=get_practice_supervisor_panel_kb(),
        )
    await state.clear()


# --------------------------------------------------------------------------- #
#           3. Поиск участницы (просмотр карточки, без обратной связи)        #
# --------------------------------------------------------------------------- #


@dp.callback_query(F.data == "p_participants", IsAdmin())
async def ps_start_search(cb: CallbackQuery, state: FSMContext) -> None:
    """Кнопка «Информация об участницах» — переходим в inline-поиск."""
    await state.set_state(PSParticipantSearch.WaitingInline)
    await state.update_data(prompt_msg_id=cb.message.message_id)

    kb = InlineKeyboardBuilder()
    kb.button(text="🔍 Найти участницу", switch_inline_query_current_chat="fio: ")
    kb.button(text="🔙 В меню", callback_data="p_menu")

    try:
        await cb.message.edit_text(
            "Введите ФИО участницы:",
            reply_markup=kb.adjust(1).as_markup(),
        )
    except TelegramBadRequest:
        # если старое сообщение нельзя редактировать
        await cb.message.delete()
        await cb.message.answer(
            "Введите ФИО участницы:",
            reply_markup=kb.adjust(1).as_markup(),
        )
    await cb.answer()


@dp.message(PSParticipantSearch.WaitingInline, F.text.startswith("#UID"), IsAdmin())
async def ps_show_card(msg: Message, state: FSMContext) -> None:
    """РП прислал «#UID123» — показываем карточку участницы + фото."""
    try:
        uid = int(msg.text[4:])
    except ValueError:
        return  # формат неправильный

    card = get_participant_card(uid)
    if not card:
        return await msg.answer("Не удалось загрузить данные")

    text = build_admin_card_text(card)
    photo_obj = get_photo_or_none(card)
    data = await state.get_data()
    prompt_id: Optional[int] = data.get("prompt_msg_id")

    try:
        if photo_obj and prompt_id:
            await bot.edit_message_media(
                chat_id=msg.chat.id,
                message_id=prompt_id,
                media=InputMediaPhoto(media=photo_obj, caption=text, parse_mode="HTML"),
                reply_markup=back_to_menu_p_kb(),
            )
        elif prompt_id:
            await bot.edit_message_text(
                chat_id=msg.chat.id,
                message_id=prompt_id,
                text=text,
                parse_mode="HTML",
                reply_markup=back_to_menu_p_kb(),
            )
        else:
            raise TelegramBadRequest
    except TelegramBadRequest:
        # fallback — новое сообщение
        if photo_obj:
            await bot.send_photo(
                chat_id=msg.chat.id,
                photo=photo_obj,
                caption=text,
                parse_mode="HTML",
                reply_markup=back_to_menu_p_kb(),
            )
        else:
            await msg.answer(text, parse_mode="HTML", reply_markup=back_to_menu_p_kb())

    with contextlib.suppress(TelegramAPIError):
        await msg.delete()


# --------------------------------------------------------------------------- #
#                4. ОС по участнице (многошаговая форма)                      #
# --------------------------------------------------------------------------- #


@dp.callback_query(F.data == "p_os", IsAdmin())
async def pfb_start(cb: CallbackQuery, state: FSMContext) -> None:
    """Старт сбора обратной связи (ОС)."""
    if not get_bool_setting("os_enabled", False):
        return await cb.answer("На данный момент сбор обратной связи не проводится.", show_alert=True)

    await state.set_state(PracticeFeedback.WaitingInline)
    await state.update_data(prompt_msg_id=cb.message.message_id)

    kb = InlineKeyboardBuilder()
    kb.button(text="🔍 Найти участницу", switch_inline_query_current_chat="fio: ")
    kb.button(text="🔙 В меню", callback_data="p_menu")

    await cb.message.edit_text("Введите ФИО участницы для ОС:", reply_markup=kb.adjust(1).as_markup())
    await cb.answer()


# -------------- inline-поиск ФИО (используется и в поиске, и в ОС) ----------


@dp.inline_query(StateFilter(PracticeFeedback.WaitingInline, PSParticipantSearch.WaitingInline), IsAdmin())
async def ps_inline_fio(iq: types.InlineQuery) -> None:
    """Inline-query-поиск ФИО (с фильтрацией по департаменту РП)."""
    text = iq.query.strip()
    if text.lower().startswith("fio:"):
        text = text[4:].lstrip()

    if len(text) < 2:
        return await iq.answer([], cache_time=1)

    users = search_users_by_fio(
        query=text,
        limit=25,
        is_bot_user=False,
        ps_user_id=iq.from_user.id,
    )
    if not users:
        return await iq.answer([], cache_time=1, switch_pm_text="Не найдено", switch_pm_parameter="not_found")

    results: list[InlineQueryResultArticle] = [
        InlineQueryResultArticle(
            id=f"uid_{u['id']}",
            title=u["full_name"],
            description=f"Тик: {u['tik']}",
            input_message_content=InputTextMessageContent(message_text=f"#UID{u['id']}"),
        )
        for u in users
    ]
    await iq.answer(results, cache_time=1)


# ---------- шаг 1: выбрана участница, оцениваем ЗКА -------------------------


@dp.message(PracticeFeedback.WaitingInline, F.text.startswith("#UID"), IsAdmin())
async def pfb_got_uid(msg: Message, state: FSMContext) -> None:
    """
    Пользователь выбрал участницу → переходим к выбору ЗКА (1–3).

    callback-data шкалы: ``pfb_zka:{uid}:{value}``
    """
    try:
        uid = int(msg.text[4:])
    except ValueError:
        return

    card = get_participant_card(uid)
    if not card:
        return await msg.answer("Не удалось загрузить данные")

    await state.update_data(user_id=uid)

    kb = scale_kb("pfb_zka", str(uid))
    text = build_admin_card_text(card) + "\n\n<b>Оцените ЗКА (1–3):</b>"

    data = await state.get_data()
    prompt_id: Optional[int] = data.get("prompt_msg_id")
    photo_obj = get_photo_or_none(card)

    if photo_obj and prompt_id:
        await bot.edit_message_media(
            chat_id=msg.chat.id,
            message_id=prompt_id,
            media=InputMediaPhoto(media=photo_obj, caption=text, parse_mode="HTML"),
            reply_markup=kb,
        )
    elif prompt_id:
        await bot.edit_message_text(
            chat_id=msg.chat.id,
            message_id=prompt_id,
            text=text,
            parse_mode="HTML",
            reply_markup=kb,
        )
    else:
        # на всякий случай
        if photo_obj:
            await bot.send_photo(msg.chat.id, photo=photo_obj, caption=text, parse_mode="HTML", reply_markup=kb)
        else:
            await msg.answer(text, parse_mode="HTML", reply_markup=kb)

    await state.set_state(PracticeFeedback.WaitZka)
    await msg.delete()


# ---------- шаг 2: ЗКА → выбор ЗКО -----------------------------------------


@dp.callback_query(PracticeFeedback.WaitZka, F.data.startswith("pfb_zka:"), IsAdmin())
async def pfb_choose_zko(cb: CallbackQuery, state: FSMContext) -> None:
    """
    ``pfb_zka:{uid}:{zka}`` → показываем шкалу ЗКО.
    """
    _, uid_str, zka_str = cb.data.split(":")
    uid, zka = int(uid_str), int(zka_str)
    await state.update_data(zka=zka)

    kb = scale_kb("pfb_zko", f"{uid}:{zka}")
    await cb.message.edit_text("<b>Оцените ЗKO (1–3):</b>", reply_markup=kb, parse_mode="HTML")
    await state.set_state(PracticeFeedback.WaitZko)
    await cb.answer()


# ---------- шаг 3: ЗКО → ввод SMART-feedback --------------------------------


@dp.callback_query(PracticeFeedback.WaitZko, F.data.startswith("pfb_zko:"), IsAdmin())
async def pfb_ask_feedback(cb: CallbackQuery, state: FSMContext) -> None:
    """
    ``pfb_zko:{uid}:{zka}:{zko}`` → просим SMART-обратную связь.
    """
    _, uid_str, zka_str, zko_str = cb.data.split(":")
    uid, zka, zko = int(uid_str), int(zka_str), int(zko_str)
    await state.update_data(zko=zko)

    kb = back_from_fb_kb(f"{uid}:{zka}:{zko}")
    await cb.message.edit_text(
        "<b>Оставьте SMART-обратную связь об участнице:</b>\n\n"
        "Пример: Ответственный, амбициозный…",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await state.set_state(PracticeFeedback.WaitFb)
    await cb.answer()


@dp.message(PracticeFeedback.WaitFb, F.text, IsAdmin())
async def pfb_save_feedback(msg: Message, state: FSMContext) -> None:
    """Получаем SMART-feedback и переходим к выбору пропусков."""
    fb_text = msg.text.strip()
    if len(fb_text) < 10:
        return await msg.answer("Сообщение слишком короткое, уточните детали.")

    await state.update_data(feedback=fb_text)
    data = await state.get_data()
    uid, zka, zko = data["user_id"], data["zka"], data["zko"]

    kb = absence_kb(f"{uid}:{zka}:{zko}")
    prompt_id: int = data["prompt_msg_id"]

    await bot.edit_message_text(
        chat_id=msg.chat.id,
        message_id=prompt_id,
        text="<b>Укажите количество пропусков практики:</b>",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await state.set_state(PracticeFeedback.WaitAbsence)
    await msg.delete()


# ---------- шаг 4: пропуски → финал ----------------------------------------


@dp.callback_query(PracticeFeedback.WaitAbsence, F.data.startswith("pfb_abs:"), IsAdmin())
async def pfb_finalize(cb: CallbackQuery, state: FSMContext) -> None:
    """
    ``pfb_abs:{uid}:{zka}:{zko}:{absence}`` — сохраняем и отправляем в канал.
    """
    *_, absence = cb.data.split(":")
    data = await state.get_data()
    data["absence"] = absence
    data["sup_id"] = cb.from_user.id

    save_practice_feedback(data)

    absence_human = (
        absence.replace(">4", "больше 4")
        .replace("<4", "меньше 4")
        .replace("minimum", "по уважительной причине")
        .replace("0", "нет")
    )

    report = (
        "📋 <b>ОС по участнице</b>\n"
        f"ID: {data['user_id']}\n\n"
        f"ЗКА: {data['zka']}   |   ЗКО: {data['zko']}\n"
        f"Пропуски: {absence_human}\n\n"
        f"📝 <b>SMART-обратная связь:</b>\n{escape(data.get('feedback', '—'))}\n\n"
        f"👤 {html.quote(cb.from_user.full_name)}"
        f"{f' (@{cb.from_user.username})' if cb.from_user.username else ''}"
    )
    await bot.send_message(feedback_chat_id, report, parse_mode="HTML")

    await cb.message.edit_text("✅ ОС успешно сохранена!", reply_markup=back_menu_p_kb())
    await state.clear()
    await cb.answer()
