"""
Handlers for the “Events” block in the Super-Admin panel.

Возможности
-----------
• Просмотр активных / удалённых мероприятий (пагинация).  
• Создание нового мероприятия (многошаговая форма).  
• Редактирование названия / описания / даты / дедлайна отчётов.  
• Удаление (soft-delete) и восстановление.  

FSM-состояния перечислены в `states.py`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from aiogram import F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from admins.filters.is_admin import IsAdmin
from admins.superadmin.events.keyboards import (
    _human,
    confirm_delete_kb,
    deadline_kb,
    event_menu_kb,
    keep_kb,
    list_kb,
    manage_kb,
)
from admins.superadmin.events.states import EventFSM
from admins.superadmin.mailing.keyboards import confirm_kb
from config import bot, dp
from db.database import (
    conn,
    create_event,
    cursor,
    get_all_events,
    get_event_by_id,
)

# --- общие константы ------------------------------------------------------- #
FMT_ISO = "%Y-%m-%d %H:%M:%S"       # БД
FMT_RU = "%d.%m.%Y %H:%M"           # human friendly (RU)


# --------------------------------------------------------------------------- #
#                           ВСПОМОГАТЕЛЬНЫЕ                                   #
# --------------------------------------------------------------------------- #
def _format_event(ev: dict) -> str:
    """
    Человекочитаемая карточка мероприятия.

    Parameters
    ----------
    ev : dict
        Строка из таблицы `events`.
    """
    deadline_part = (
        f"\n⏰ <i>до {_human(ev.get('report_deadline'))}</i>"
        if ev.get("report_deadline")
        else ""
    )
    return (
        f"<b>{ev.get('title')}</b>\n\n"
        f"{ev.get('description') or '—'}\n\n"
        f"📅 <i>{_human(ev.get('event_date'))}</i>{deadline_part}"
    )


async def _send_event_card(
    message: types.Message,
    ev: dict,
    state: FSMContext,
    *,
    replace_msg: bool = True,
) -> None:
    """
    Показать или обновить карточку мероприятия.

    If ``replace_msg`` is True — редактирует исходное сообщение,
    иначе шлёт новое под ним.
    """
    text = _format_event(ev)
    kb = event_menu_kb(ev["id"], ev["status"] == "deleted")

    if replace_msg:
        await message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=kb)

    await state.set_state(EventFSM.EventMenu)
    await state.update_data(ev_id=ev["id"])


def _update_event_field(ev_id: int, field: str, val: str) -> None:
    """
    Безопасное обновление одного поля события.

    NB: поле подставляется *из кода*, а не от пользователя,
    чтобы исключить SQL-инъекции. Значения передаются параметризировано.
    """
    assert field in {"title", "description", "event_date"}  # safety-net
    cursor.execute(f"UPDATE events SET {field} = ? WHERE id = ?", (val, ev_id))
    conn.commit()


def _parse_dt(dt_str: str) -> datetime:
    """Пробует ISO и RU-форматы, иначе бросает ValueError."""
    for fmt in (FMT_ISO, FMT_RU):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    raise ValueError("bad date string")


# --------------------------------------------------------------------------- #
#                        ГЛАВНОЕ МЕНЮ («Мероприятия»)                          #
# --------------------------------------------------------------------------- #
@dp.callback_query(F.data == "sa_events", IsAdmin())
async def ev_manage_main(cb: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EventFSM.SelectAction)
    await cb.message.edit_text("Управление мероприятиями:", reply_markup=manage_kb())
    await cb.answer()


@dp.callback_query(EventFSM.SelectAction, F.data.startswith("ev_list:"), IsAdmin())
async def ev_list(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Отображение списка (по статусу) + пагинация."""
    _, page_s, status = cb.data.split(":")
    page = int(page_s)
    events = get_all_events(status)

    await state.set_state(EventFSM.ListEvents)
    await state.update_data(events=events, status=status)

    lines: List[str] = [
        f"• {_human(ev['event_date'])} — <b>{ev['title']}</b>" for ev in events
    ]
    header = "Неактивные мероприятия:" if status == "deleted" else "Активные мероприятия:"
    await cb.message.edit_text(
        header + "\n" + "\n".join(lines),
        parse_mode="HTML",
        reply_markup=list_kb(events, page, status),
    )
    await cb.answer()


# --- «Назад» из разных точек ------------------------------------------------ #
@dp.callback_query(F.data.in_({"ev_back_trash", "ev_back_main"}), IsAdmin())
async def ev_back_to_root(cb: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EventFSM.SelectAction)
    await cb.message.edit_text("Управление мероприятиями:", reply_markup=manage_kb())
    await cb.answer()


# --------------------------------------------------------------------------- #
#                      КАРТОЧКА / УДАЛЕНИЕ / ВОССТАНОВЛЕНИЕ                   #
# --------------------------------------------------------------------------- #
@dp.callback_query(EventFSM.ListEvents, F.data.startswith("ev_open:"), IsAdmin())
async def ev_open(cb: types.CallbackQuery, state: FSMContext) -> None:
    ev_id = int(cb.data.split(":")[1])
    ev = get_event_by_id(ev_id)
    if not ev:
        return await cb.answer("Мероприятие не найдено", show_alert=True)

    await _send_event_card(cb.message, ev, state)
    await cb.answer()


@dp.callback_query(EventFSM.EventMenu, F.data.startswith("ev_del_confirm:"), IsAdmin())
async def ev_del_confirm(cb: types.CallbackQuery) -> None:
    ev_id = int(cb.data.split(":")[1])
    await cb.message.edit_text(
        "Вы уверены, что хотите удалить мероприятие?",
        reply_markup=confirm_delete_kb(ev_id),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("ev_delete:"), IsAdmin())
async def ev_delete(cb: types.CallbackQuery, state: FSMContext) -> None:
    ev_id = int(cb.data.split(":")[1])
    cursor.execute("UPDATE events SET status = 'deleted' WHERE id = ?", (ev_id,))
    conn.commit()

    await cb.message.edit_text("🗑 Мероприятие перемещено в корзину.", reply_markup=manage_kb())
    await state.set_state(EventFSM.SelectAction)
    await cb.answer()


@dp.callback_query(F.data.startswith("ev_restore:"), IsAdmin())
async def ev_restore(cb: types.CallbackQuery, state: FSMContext) -> None:
    ev_id = int(cb.data.split(":")[1])
    cursor.execute(
        "UPDATE events SET status = 'active', report_deadline = NULL WHERE id = ?",
        (ev_id,),
    )
    conn.commit()

    await cb.message.edit_text("✅ Мероприятие восстановлено.", reply_markup=manage_kb())
    await state.set_state(EventFSM.SelectAction)
    await cb.answer()


@dp.callback_query(F.data.startswith("ev_back_list"), IsAdmin())
async def ev_back_list(cb: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    events = data.get("events") or get_all_events()
    status = data.get("status", "active")

    await state.set_state(EventFSM.ListEvents)
    await cb.message.edit_text(
        "Список мероприятий:",
        reply_markup=list_kb(events, 0, status),
    )
    await cb.answer()


# --------------------------------------------------------------------------- #
#                          СОЗДАНИЕ   (многошагово)                           #
# --------------------------------------------------------------------------- #
@dp.callback_query(EventFSM.SelectAction, F.data == "ev_create_start", IsAdmin())
async def ev_start_create(cb: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EventFSM.CreateTitle)
    await state.update_data(events_create_msg_id=cb.message.message_id)

    await cb.message.edit_text(
        "Введите <b>название</b> мероприятия:",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text="Назад", callback_data="ev_back_main")]]
        ),
    )
    await cb.answer()


@dp.message(EventFSM.CreateTitle, IsAdmin())
async def ev_create_title(msg: types.Message, state: FSMContext) -> None:
    await state.update_data(new_title=msg.text.strip())

    data = await state.get_data()
    await bot.edit_message_text(
        "Введите <b>описание</b> мероприятия:",
        chat_id=msg.chat.id,
        message_id=data["events_create_msg_id"],
        parse_mode="HTML",
    )
    await state.set_state(EventFSM.CreateDesc)
    await msg.delete()


@dp.message(EventFSM.CreateDesc, IsAdmin())
async def ev_create_desc(msg: types.Message, state: FSMContext) -> None:
    await state.update_data(new_desc=msg.text.strip())

    data = await state.get_data()
    await bot.edit_message_text(
        "Введите <b>дату</b> мероприятия в формате <code>DD.MM.YYYY HH:MM</code>:",
        chat_id=msg.chat.id,
        message_id=data["events_create_msg_id"],
        parse_mode="HTML",
    )
    await state.set_state(EventFSM.CreateDate)
    await msg.delete()


@dp.message(EventFSM.CreateDate, IsAdmin())
async def ev_create_date(msg: types.Message, state: FSMContext) -> None:
    date_str = msg.text.strip()
    try:
        dt = datetime.strptime(date_str, "%d.%m.%Y %H:%M")
    except ValueError:
        return await msg.answer("Некорректный формат. Попробуйте ещё раз.")

    await state.update_data(new_date=dt.strftime(FMT_ISO))
    data = await state.get_data()

    preview = (
        f"<b>{data['new_title']}</b>\n"
        f"{data['new_desc']}\n"
        f"📅 <i>{date_str}</i>"
    )
    await bot.edit_message_text(
        chat_id=msg.chat.id,
        message_id=data["events_create_msg_id"],
        text=f"Проверьте данные:\n\n{preview}",
        parse_mode="HTML",
        reply_markup=confirm_kb(),
    )
    await state.set_state(EventFSM.ConfirmCreate)
    await msg.delete()


@dp.callback_query(EventFSM.ConfirmCreate, F.data == "ml_send", IsAdmin())
async def ev_save(cb: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    ev_id = create_event(data["new_title"], data["new_desc"], data["new_date"])

    if not ev_id:
        return await cb.answer("Ошибка при сохранении.", show_alert=True)

    await state.clear()
    await cb.message.edit_text("Мероприятие успешно создано ✅", reply_markup=manage_kb())
    await cb.answer()


@dp.callback_query(EventFSM.ConfirmCreate, F.data == "ml_cancel", IsAdmin())
async def ev_create_cancel(cb: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text("Создание отменено.", reply_markup=manage_kb())
    await cb.answer()


# --------------------------------------------------------------------------- #
#                              РЕДАКТИРОВАНИЕ                                 #
# --------------------------------------------------------------------------- #
@dp.callback_query(EventFSM.EventMenu, F.data.startswith("ev_edit_title:"), IsAdmin())
async def ev_edit_title_start(cb: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EventFSM.EditTitle)
    await cb.message.edit_text("Введите новое <b>название</b>:", parse_mode="HTML", reply_markup=keep_kb)
    await cb.answer()


@dp.message(EventFSM.EditTitle, IsAdmin())
async def ev_edit_title_save(msg: types.Message, state: FSMContext) -> None:
    ev_id = (await state.get_data())["ev_id"]
    _update_event_field(ev_id, "title", msg.text.strip())

    await _send_event_card(msg, get_event_by_id(ev_id), state, replace_msg=False)
    await msg.delete()


@dp.callback_query(EventFSM.EventMenu, F.data.startswith("ev_edit_desc:"), IsAdmin())
async def ev_edit_desc_start(cb: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EventFSM.EditDesc)
    await cb.message.edit_text("Введите новое <b>описание</b>:", parse_mode="HTML", reply_markup=keep_kb)
    await cb.answer()


@dp.message(EventFSM.EditDesc, IsAdmin())
async def ev_edit_desc_save(msg: types.Message, state: FSMContext) -> None:
    ev_id = (await state.get_data())["ev_id"]
    _update_event_field(ev_id, "description", msg.text.strip())

    await _send_event_card(msg, get_event_by_id(ev_id), state, replace_msg=False)
    await msg.delete()


@dp.callback_query(EventFSM.EventMenu, F.data.startswith("ev_edit_date:"), IsAdmin())
async def ev_edit_date_start(cb: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EventFSM.EditDate)
    await cb.message.edit_text(
        "Введите новую дату в формате <code>DD.MM.YYYY HH:MM</code>:",
        parse_mode="HTML",
        reply_markup=keep_kb,
    )
    await cb.answer()


@dp.message(EventFSM.EditDate, IsAdmin())
async def ev_edit_date_save(msg: types.Message, state: FSMContext) -> None:
    try:
        dt = datetime.strptime(msg.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        return await msg.answer("Некорректный формат. Попробуйте снова.")

    ev_id = (await state.get_data())["ev_id"]
    _update_event_field(ev_id, "event_date", dt.strftime(FMT_ISO))

    await _send_event_card(msg, get_event_by_id(ev_id), state, replace_msg=False)
    await msg.delete()


# --------------------------------------------------------------------------- #
#                           ДЕДЛАЙНЫ  ОТЧЁТОВ                                 #
# --------------------------------------------------------------------------- #
@dp.callback_query(EventFSM.EventMenu, F.data.startswith("ev_edit_deadline:"), IsAdmin())
async def ev_deadline_menu(cb: types.CallbackQuery) -> None:
    ev_id = int(cb.data.split(":")[1])
    await cb.message.edit_text("Прекратить сбор отчётов через …", reply_markup=deadline_kb(ev_id))
    await cb.answer()


@dp.callback_query(F.data.startswith("ev_set_deadline:"), IsAdmin())
async def ev_set_deadline(cb: types.CallbackQuery, state: FSMContext) -> None:
    _, ev_id_s, hours_s = cb.data.split(":")
    ev_id, hours = int(ev_id_s), int(hours_s)

    ev = get_event_by_id(ev_id)
    if not ev:
        return await cb.answer("Мероприятие не найдено.", show_alert=True)

    if hours == 0:
        cursor.execute("UPDATE events SET report_deadline = NULL WHERE id = ?", (ev_id,))
        text = "Срок сбора отчётов удалён."
    else:
        base = _parse_dt(ev["event_date"])
        deadline_iso = (base + timedelta(hours=hours)).strftime(FMT_ISO)
        cursor.execute("UPDATE events SET report_deadline = ? WHERE id = ?", (deadline_iso, ev_id))
        text = f"Отчёты принимаются до: {_human(deadline_iso)}"

    conn.commit()
    await _send_event_card(cb.message, get_event_by_id(ev_id), state, replace_msg=True)
    await cb.answer(text)


# --- «Оставить текущее» на этапе редактирования ---------------------------- #
@dp.callback_query(F.data == "ev_keep", IsAdmin())
async def ev_keep_field(cb: types.CallbackQuery, state: FSMContext) -> None:
    ev_id = (await state.get_data())["ev_id"]
    await _send_event_card(cb.message, get_event_by_id(ev_id), state)
    await cb.answer()
