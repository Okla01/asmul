"""
Inline-клавиатуры для блока «Мероприятия».
"""

from __future__ import annotations

from datetime import datetime
from math import ceil
from typing import List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --------------------------------------------------------------------------- #
#                           ВСПОМОГАТЕЛЬНЫЕ                                   #
# --------------------------------------------------------------------------- #
def _human(dt_str: str | None) -> str:
    """
    Приводит строку-дату к виду «DD.MM.YYYY HH:MM» или возвращает «—».

    Поддерживает ISO (`%Y-%m-%d %H:%M:%S`) и RU (`%d.%m.%Y %H:%M`) форматы.
    """
    if not dt_str:
        return "—"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(dt_str, fmt).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            continue
    return dt_str


# --------------------------------------------------------------------------- #
#                               ГЛАВНОЕ МЕНЮ                                  #
# --------------------------------------------------------------------------- #
def manage_kb() -> InlineKeyboardMarkup:
    """Показывает счётчики активных / удалённых + кнопку «Создать»."""
    from db.database import get_all_events  # лок. импорт → избегаем циклов

    active_cnt = len(get_all_events("active"))
    deleted_cnt = len(get_all_events("deleted"))

    kb = InlineKeyboardBuilder()
    kb.button(text=f"Активные ({active_cnt})", callback_data="ev_list:0:active")
    kb.button(text=f"Неактивные ({deleted_cnt})", callback_data="ev_list:0:deleted")
    kb.button(text="Создать", callback_data="ev_create_start")
    kb.button(text="Назад", callback_data="sa_menu")
    return kb.adjust(1).as_markup()


# --------------------------------------------------------------------------- #
#                              СПИСОК  (пагинация)                            #
# --------------------------------------------------------------------------- #
def list_kb(
    events: List[dict],
    page: int,
    status: str,
    *,
    per_page: int = 6,
) -> InlineKeyboardMarkup:
    """
    Клавиатура постраничного списка мероприятий.

    *events* — полный список (мы сами режем по `page`).  
    *page*   — 0-based номер страницы.  
    *status* — «active» / «deleted».
    """
    total = len(events)
    pages = max(1, ceil(total / per_page))
    page = max(0, min(page, pages - 1))

    start, stop = page * per_page, min(page * per_page + per_page, total)
    kb = InlineKeyboardBuilder()

    # --- список событий ---
    for ev in events[start:stop]:
        title = ev["title"][:40]
        label = f"{_human(ev['event_date'])} | {title}"
        if ev.get("report_deadline"):
            label = f"⏰ {label}"
        kb.button(text=label, callback_data=f"ev_open:{ev['id']}")
    kb.adjust(1)

    # --- навигация ---
    if pages > 1:
        kb.row(
            InlineKeyboardButton(text="«", callback_data=f"ev_list:0:{status}"),
            InlineKeyboardButton(text="‹", callback_data=f"ev_list:{page - 1}:{status}"),
            InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="ev_curr"),
            InlineKeyboardButton(text="›", callback_data=f"ev_list:{page + 1}:{status}"),
            InlineKeyboardButton(text="»", callback_data=f"ev_list:{pages - 1}:{status}"),
        )

    back_cb = "ev_back_main" if status == "active" else "ev_back_trash"
    kb.row(InlineKeyboardButton(text="Назад", callback_data=back_cb))
    return kb.as_markup()


# --------------------------------------------------------------------------- #
#                           МЕНЮ  ОДНОГО  СОБЫТИЯ                             #
# --------------------------------------------------------------------------- #
def event_menu_kb(ev_id: int, deleted: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if not deleted:
        kb.button(text="Изменить название", callback_data=f"ev_edit_title:{ev_id}")
        kb.button(text="Изменить описание", callback_data=f"ev_edit_desc:{ev_id}")
        kb.button(text="Изменить дату", callback_data=f"ev_edit_date:{ev_id}")
        kb.button(text="Изменить срок отчётов", callback_data=f"ev_edit_deadline:{ev_id}")
        kb.button(text="Удалить", callback_data=f"ev_del_confirm:{ev_id}")
    else:
        kb.button(text="Восстановить", callback_data=f"ev_restore:{ev_id}")
    kb.button(text="Назад", callback_data="ev_back_list")
    return kb.adjust(1).as_markup()


def deadline_kb(ev_id: int) -> InlineKeyboardMarkup:
    """Выбор дедлайна в часах от времени события."""
    kb = InlineKeyboardBuilder()
    for hours, label in [(12, "12 часов"), (24, "1 день"), (48, "2 дня"), (96, "4 дня")]:
        kb.button(text=f"Через {label}", callback_data=f"ev_set_deadline:{ev_id}:{hours}")
    kb.button(text="Убрать дедлайн", callback_data=f"ev_set_deadline:{ev_id}:0")
    kb.button(text="Назад", callback_data=f"ev_open:{ev_id}")
    kb.adjust(1)
    return kb.as_markup()


def confirm_delete_kb(ev_id: int) -> InlineKeyboardMarkup:
    """Подтверждение удаления."""
    kb = InlineKeyboardBuilder()
    kb.button(text="Удалить", callback_data=f"ev_delete:{ev_id}")
    kb.button(text="Назад", callback_data=f"ev_open:{ev_id}")
    return kb.adjust(1).as_markup()


# ― кнопка «Оставить текущее» (используется при редактировании) ―
keep_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Оставить текущее", callback_data="ev_keep")],
        [InlineKeyboardButton(text="Назад", callback_data="ev_back_event")],
    ]
)
