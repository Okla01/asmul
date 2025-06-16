"""
Handlers блока «Экспорт отчётов / статистика» суперадмина.

Полноценный, неурезанный файл. Структура:
  • главное меню / выбор отчёта;
  • статистика;
  • экспорт (отсутствия — выбор объектов → даты → формат → выгрузка);
  • вспомогательные функции + «Назад».
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from textwrap import shorten

from aiogram import F, html, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram_dialog import DialogManager, StartMode

from admins.filters.is_admin import IsAdmin
from admins.superadmin.reports.calendar import rep_calendar_dialog
from admins.superadmin.reports.exporter import export_report
from admins.superadmin.reports.keyboards import (
    absence_obj_kb,
    date_choose_kb,
    format_kb,
    reports_main_kb,
)
from admins.superadmin.reports.states import RepFSM
from config import LOCATION_NAMES, bot, dp
from db.database import conn


# ──────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ
# ──────────────────────────────────────────

def _today() -> str:
    """Текущий день DD.MM.YYYY (Europe/Helsinki)."""
    return datetime.now().strftime("%d.%m.%Y")


async def _edit_safe(msg: types.Message,
              *,
              text: str,
              reply_markup: Optional[InlineKeyboardMarkup] = None,
              parse_mode: str = "HTML") -> None:
    """Безопасный edit_text — если нельзя, отправляем новое."""
    try:
        await msg.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except TelegramBadRequest:
        await msg.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)


# ──────────────────────────────────────────
# 1. ГЛАВНОЕ МЕНЮ
# ──────────────────────────────────────────

@dp.callback_query(F.data == "sa_export", IsAdmin())
async def rep_main(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Показать главное меню блока «Отчёты/статистика»."""
    await state.clear()
    await state.set_state(RepFSM.Main)
    await cb.message.edit_text("Выберите отчёт:", reply_markup=reports_main_kb())
    await cb.answer()


@dp.callback_query(RepFSM.Main, F.data.startswith("rep_"), IsAdmin())
async def rep_choose_report(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Обработка клика по пункту в главном меню."""
    cmd = cb.data
    if cmd == "rep_stats":
        return await _show_stats(cb, state)

    # экспорт отчёта
    kind = cmd.split("_", 1)[1]  # clean / events / violations / absence
    await state.update_data(report_kind=kind)

    if kind == "absence":
        # шаг 1 — выбор объектов (локаций)
        await state.set_state(RepFSM.ChooseAbsObj)
        await cb.message.edit_text(
            "Выберите объекты (можно несколько):",
            reply_markup=absence_obj_kb([]),
        )
    else:
        # сразу к диапазону дат
        await _ask_start_date(cb, state, back_cb="rep_back2main")
    await cb.answer()


# ──────────────────────────────────────────
# 2. СТАТИСТИКА
# ──────────────────────────────────────────

async def _show_stats(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Формирует и выводит агрегированную статистику по четырём таблицам."""
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM room_cleanliness_reports")
    clean_cnt = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM event_attendance WHERE attended = 1")
    events_cnt = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM violations")
    viol_cnt = cur.fetchone()[0]

    cur.execute("SELECT place, COUNT(*) FROM absences GROUP BY place")
    abs_rows = cur.fetchall()

    lines = [
        f"🧹 Отчётов чистоты: <b>{clean_cnt}</b>",
        f"📅 Посещений мероприятий: <b>{events_cnt}</b>",
        f"🚔 Нарушений: <b>{viol_cnt}</b>",
        "",
        "🚪 <b>Отсутствия по объектам</b>:",
    ]
    for place, cnt in abs_rows:
        lines.append(f"  • {LOCATION_NAMES.get(place, place)} — {cnt}")

    await state.set_state(RepFSM.StatsShow)
    await cb.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup.inline_keyboard(
            [[InlineKeyboardButton(text="Назад", callback_data="rep_back2main")]]
        ),
    )
    await cb.answer()


# ──────────────────────────────────────────
# 3. ОТСУТСТВИЯ — ВЫБОР ОБЪЕКТОВ
# ──────────────────────────────────────────

@dp.callback_query(RepFSM.ChooseAbsObj, F.data.startswith("rep_absobj:"), IsAdmin())
async def rep_abs_toggle_obj(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Чекбоксы объектов: добавляет/удаляет код в списке ``absence_objs``."""
    code = cb.data.split(":")[1]
    data = await state.get_data()
    chosen: List[str] = data.get("absence_objs", [])
    chosen = [*chosen, code] if code not in chosen else [c for c in chosen if c != code]
    await state.update_data(absence_objs=chosen)
    await cb.message.edit_reply_markup(reply_markup=absence_obj_kb(chosen))
    await cb.answer()


@dp.callback_query(RepFSM.ChooseAbsObj, F.data == "rep_abs_confirm", IsAdmin())
async def rep_abs_confirm_objs(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Переход к выбору дат после подтверждения объектов."""
    if not (await state.get_data()).get("absence_objs"):
        return await cb.answer("Нужно выбрать хотя бы один объект.", show_alert=True)

    await _ask_start_date(cb, state, back_cb="rep_back2main")
    await cb.answer()


# ──────────────────────────────────────────
# 4. ВЫБОР ДАТ
# ──────────────────────────────────────────

async def _ask_start_date(cb: types.CallbackQuery, state: FSMContext, *, back_cb: str) -> None:
    """Запрашиваем дату начала."""
    await state.set_state(RepFSM.ChooseStart)
    await cb.message.edit_text(
        "Выберите <b>начальную</b> дату:",
        parse_mode="HTML",
        reply_markup=date_choose_kb(back_cb),
    )


async def _ask_end_date(src: types.Message | types.CallbackQuery, state: FSMContext) -> None:
    """Запрашиваем дату конца."""
    await state.set_state(RepFSM.ChooseEnd)
    data = await state.get_data()
    txt = f"Начало: <b>{data['start']}</b>\n\nТеперь выберите <b>конечную</b> дату:"
    tgt = src.message if isinstance(src, types.CallbackQuery) else src
    await _edit_safe(tgt, text=txt, reply_markup=date_choose_kb("rep_back2start"))


@dp.callback_query(RepFSM.ChooseStart, F.data == "rep_date:today", IsAdmin())
async def rep_start_today(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Кнопка «Сегодня» для начальной даты."""
    await state.update_data(start=_today())
    await _ask_end_date(cb, state)
    await cb.answer()


@dp.callback_query(RepFSM.ChooseEnd, F.data == "rep_date:today", IsAdmin())
async def rep_end_today(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Кнопка «Сегодня» для конечной даты."""
    await state.update_data(end=_today())
    await _ask_format(cb, state)
    await cb.answer()


@dp.callback_query(RepFSM.ChooseStart, F.data == "rep_date:cal", IsAdmin())
async def rep_start_calendar(cb: types.CallbackQuery, state: FSMContext, dialog_manager: DialogManager) -> None:
    """Открыть календарь для начальной даты."""
    dialog_manager.start(rep_calendar_dialog, StartMode.NORMAL,
                         start_data={"step": "start", "fsm": state})
    await cb.answer()


@dp.callback_query(RepFSM.ChooseEnd, F.data == "rep_date:cal", IsAdmin())
async def rep_end_calendar(cb: types.CallbackQuery, state: FSMContext, dialog_manager: DialogManager) -> None:
    """Открыть календарь для конечной даты."""
    dialog_manager.start(rep_calendar_dialog, StartMode.NORMAL,
                         start_data={"step": "end", "fsm": state})
    await cb.answer()


async def back_from_calendar(c: types.CallbackQuery, mgr: DialogManager) -> None:
    """Вызывается после выбора даты в календаре."""
    fsm: FSMContext = mgr.start_data["fsm"]
    data = await fsm.get_data()
    if "start" in data and "end" not in data:
        await _ask_end_date(c, fsm)
    elif "start" in data and "end" in data:
        await _ask_format(c, fsm)


# ──────────────────────────────────────────
# 5. ФОРМАТ
# ──────────────────────────────────────────

async def _ask_format(src: types.Message | types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(RepFSM.ChooseFormat)
    data = await state.get_data()
    txt = (
        f"Начало: <b>{data['start']}</b>\n"
        f"Конец: <b>{data['end']}</b>\n\n"
        "Выберите формат файла:"
    )
    tgt = src.message if isinstance(src, types.CallbackQuery) else src
    await _edit_safe(tgt, text=txt, reply_markup=format_kb())


@dp.callback_query(RepFSM.ChooseFormat, F.data.startswith("rep_fmt:"), IsAdmin())
async def rep_do_export(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Формируем и отправляем отчёт."""
    fmt = cb.data.split(":")[1]
    data = await state.get_data()

    await cb.answer("Формирую отчёт, это может занять время…", show_alert=True)
    try:
        zip_path = await export_report(
            kind=data["report_kind"],
            date_from=data["start"],
            date_to=data["end"],
            fmt=fmt,
            abs_places=data.get("absence_objs"),
        )
    except Exception as exc:  # pylint: disable=broad-except
        await _edit_safe(cb.message, text=f"❗️ Ошибка: {html.quote(str(exc))}")
        await state.clear()
        return

    await bot.send_document(cb.from_user.id, FSInputFile(zip_path))
    await cb.message.edit_text("✅ Отчёт готов!", reply_markup=reports_main_kb())
    await state.set_state(RepFSM.Main)
    await cb.answer()


# ──────────────────────────────────────────
# 6. «НАЗАД»
# ──────────────────────────────────────────

@dp.callback_query(F.data == "rep_back2main", IsAdmin())
async def rep_back_main(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Возврат в главное меню отчётов."""
    await state.set_state(RepFSM.Main)
    await cb.message.edit_text("Выберите отчёт:", reply_markup=reports_main_kb())
    await cb.answer()


@dp.callback_query(F.data == "rep_back2start", IsAdmin())
async def rep_back_start(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Возврат к выбору начальной даты."""
    await _ask_start_date(cb, state, back_cb="rep_back2main")
    await cb.answer()
