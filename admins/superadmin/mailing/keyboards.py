"""
Inline-клавиатуры модуля «Рассылки».
"""

from __future__ import annotations

from typing import List, Set, Tuple

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --------------------------------------------------------------------------- #
#                             0. СТАРТОВОЕ МЕНЮ                               #
# --------------------------------------------------------------------------- #


def targets_kb() -> InlineKeyboardMarkup:
    """Главный выбор: «кому» отправляем."""
    kb = InlineKeyboardBuilder()
    kb.button(text="Участницам (по тикам)", callback_data="ml_participants")
    kb.button(text="Всем", callback_data="ml_all")
    kb.button(text="Всем сотрудникам", callback_data="ml_staff")
    kb.button(text="Кандидаткам", callback_data="ml_candidates")
    kb.button(text="📅 Запланированные", callback_data="ml_planned")
    kb.button(text="Назад", callback_data="sa_menu")
    return kb.adjust(1).as_markup()


# --------------------------------------------------------------------------- #
#                       1.  Участницы  — тики                                 #
# --------------------------------------------------------------------------- #
def tiks_kb(all_tiks: List[str], chosen: Set[str]) -> InlineKeyboardMarkup:
    """
    Чекбоксы тик-кодов.

    `all_tiks` — фиксированный полный список (порядок не меняем);  
    `chosen`   — отмеченные коды.
    """
    kb = InlineKeyboardBuilder()
    for t in all_tiks:
        mark = "✅ " if t in chosen else ""
        kb.button(text=f"{mark}{t}", callback_data=f"ml_tik_toggle:{t}")
    kb.adjust(2)

    kb.row(
        InlineKeyboardButton(text="Подтвердить", callback_data="ml_tiks_done"),
        InlineKeyboardButton(text="Назад", callback_data="ml_back_targets"),
    )
    return kb.as_markup()


# --------------------------------------------------------------------------- #
#                       2.  Сотрудники  — категории                           #
# --------------------------------------------------------------------------- #
STAFF_CATEGORIES: List[Tuple[str, str]] = [
    ("emp", "Сотрудники"),
    ("psup", "Руководители практики"),
    ("admin", "Администраторы"),
    ("supad", "Суперадмины"),
]


def staff_kb(chosen: Set[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for code, title in STAFF_CATEGORIES:
        prefix = "✅ " if code in chosen else ""
        kb.button(text=f"{prefix}{title}", callback_data=f"ml_staff_toggle:{code}")
    kb.adjust(2)

    kb.row(
        InlineKeyboardButton(text="Отправить", callback_data="ml_staff_done"),
        InlineKeyboardButton(text="Назад", callback_data="ml_back_targets"),
    )
    return kb.as_markup()


# --------------------------------------------------------------------------- #
#                       3.  Периодичность / Recurrence                        #
# --------------------------------------------------------------------------- #
def recurrence_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🟢 Один раз", callback_data="rec_once")
    kb.button(text="🔄 Каждый день", callback_data="rec_day")
    kb.button(text="📅 Каждую неделю", callback_data="rec_week")
    kb.button(text="🗓  Каждый месяц", callback_data="rec_month")
    kb.button(text="🚫 Отмена", callback_data="ml_cancel")
    return kb.adjust(1).as_markup()


# --------------------------------------------------------------------------- #
#                       4.  Подтверждения / деталка                           #
# --------------------------------------------------------------------------- #
def confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Запланировать", callback_data="ml_plan_confirm")
    kb.button(text="🚫 Отмена", callback_data="ml_cancel")
    return kb.adjust(1).as_markup()


def planned_detail_kb(mid: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Редактировать", callback_data=f"ml_planned_edit:{mid}")
    kb.button(text="🗑 Удалить", callback_data=f"ml_planned_del:{mid}")
    kb.button(text="⬅️ Назад", callback_data="ml_back_plist")
    return kb.adjust(1).as_markup()


def edit_opts_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Текст", callback_data="ml_edit_text")
    kb.button(text="📅 Дата/время", callback_data="ml_edit_dt")
    kb.button(text="🔄 Периодичность", callback_data="ml_edit_rec")
    kb.button(text="⬅️ Назад", callback_data="ml_edit_back")
    return kb.adjust(1).as_markup()
