"""
Inline-клавиатуры блока «Экспорт отчётов».
"""

from __future__ import annotations

from typing import List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import LOCATION_NAMES


# ─── Главное меню ────────────────────────────────────────────────────────── #
def reports_main_kb() -> InlineKeyboardMarkup:
    """«Статистика» + четыре вида отчётов."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data="rep_stats")
    kb.button(text="🧹 Отчёт чистоты", callback_data="rep_clean")
    kb.button(text="📅 Отчёт мероприятий", callback_data="rep_events")
    kb.button(text="🚔 Отчёт нарушений", callback_data="rep_violations")
    kb.button(text="🚪 Отчёт отсутствий", callback_data="rep_absence")
    kb.button(text="Назад", callback_data="sa_menu")
    return kb.adjust(1).as_markup()


# ─── Отсутствия: объекты ─────────────────────────────────────────────────── #
def absence_obj_kb(selected: List[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for code, title in LOCATION_NAMES.items():
        mark = "✅ " if code in selected else ""
        kb.button(text=f"{mark}{title}", callback_data=f"rep_absobj:{code}")
    kb.adjust(2)
    kb.row(
        InlineKeyboardButton(text="Подтвердить ✔️", callback_data="rep_abs_confirm"),
        InlineKeyboardButton(text="Назад", callback_data="rep_back2main"),
    )
    return kb.as_markup()


# ─── Дата: «Сегодня / Календарь» ─────────────────────────────────────────── #
def date_choose_kb(back_cb: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Сегодня", callback_data="rep_date:today")
    kb.button(text="📅 Календарь", callback_data="rep_date:cal")
    kb.button(text="Назад", callback_data=back_cb)
    return kb.adjust(1).as_markup()


# ─── Формат файла ────────────────────────────────────────────────────────── #
def format_kb() -> InlineKeyboardMarkup:
    return (
        InlineKeyboardBuilder()
        .button(text="📄 PDF", callback_data="rep_fmt:pdf")
        .button(text="📊 Excel", callback_data="rep_fmt:xlsx")
        .button(text="Назад", callback_data="rep_back2start")
        .adjust(1)
        .as_markup()
    )
