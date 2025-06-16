"""
Inline-клавиатуры для модуля «FAQ» суперадмина.
"""

from __future__ import annotations

from math import ceil
from typing import List, Tuple

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ROLES

# --------------------------------------------------------------------------- #
#                           1. ВЫБОР  РОЛИ                                    #
# --------------------------------------------------------------------------- #
_EXCLUDED_ROLES = {"admin_supervisor"}
_PER_PAGE_ROLES = 6
_MAX_COLS_ROLES = 2


def roles_kb(page: int, *, per_page: int = _PER_PAGE_ROLES) -> InlineKeyboardMarkup:
    """Список всех ролей (кроме суперадмина) с пагинацией."""
    roles: List[Tuple[str, str]] = [
        (code, ROLES[code]) for code in ROLES if code not in _EXCLUDED_ROLES
    ]
    pages = ceil(len(roles) / per_page)
    page = max(0, min(page, pages - 1))
    chunk = roles[page * per_page : (page + 1) * per_page]

    kb = InlineKeyboardBuilder()
    for code, title in chunk:
        if code == "user_unauthorized":
            kb.button(text=title, callback_data="faq_candidate")
        else:
            kb.button(text=title, callback_data=f"faq_role:{code}")
    kb.adjust(_MAX_COLS_ROLES)

    # навигация
    if pages > 1:
        first, last = 0, pages - 1
        kb.row(
            InlineKeyboardButton(text="«", callback_data=f"faq_roles_page:{first}"),
            InlineKeyboardButton(text="‹", callback_data=f"faq_roles_page:{page-1}"),
            InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="faq_roles_curr"),
            InlineKeyboardButton(text="›", callback_data=f"faq_roles_page:{page+1}"),
            InlineKeyboardButton(text="»", callback_data=f"faq_roles_page:{last}"),
        )

    kb.row(InlineKeyboardButton(text="Назад", callback_data="sa_menu"))
    return kb.as_markup()


# --------------------------------------------------------------------------- #
#                         2.  МЕНЮ  ОДНОЙ  РОЛИ                               #
# --------------------------------------------------------------------------- #
def role_menu_kb(role_code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if role_code == "user_unauthorized":
        kb.button(text="⬇️ Выгрузить FAQ", callback_data="faq_export_cand")
        kb.button(text="⬆️ Загрузить Excel", callback_data="faq_import_cand")
    else:
        kb.button(text="Список FAQ", callback_data=f"faq_list:{role_code}:0")
        kb.button(text="Создать", callback_data=f"faq_create:{role_code}")
    kb.button(text="Назад", callback_data="faq_roles_root")
    return kb.adjust(1).as_markup()


# --------------------------------------------------------------------------- #
#                       3.  СПИСОК FAQ (пагинация)                            #
# --------------------------------------------------------------------------- #
def faq_list_kb(
    role_code: str,
    page: int,
    questions: List[Tuple[int, str]],
    *,
    per_page: int = 6,
) -> InlineKeyboardMarkup:
    total = len(questions)
    pages = max(1, ceil(total / per_page))
    page = max(0, min(page, pages - 1))

    kb = InlineKeyboardBuilder()
    for qid, question in questions[page * per_page : page * per_page + per_page]:
        kb.button(text=question[:64], callback_data=f"faq_q:{role_code}:{qid}")
    kb.adjust(1)

    if pages > 1:
        kb.row(
            InlineKeyboardButton(text="«", callback_data=f"faq_list:{role_code}:0"),
            InlineKeyboardButton(text="‹", callback_data=f"faq_list:{role_code}:{page-1}"),
            InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="faq_curr"),
            InlineKeyboardButton(text="›", callback_data=f"faq_list:{role_code}:{page+1}"),
            InlineKeyboardButton(text="»", callback_data=f"faq_list:{role_code}:{pages-1}"),
        )

    kb.row(InlineKeyboardButton(text="Назад", callback_data=f"faq_role_back:{role_code}"))
    return kb.as_markup()


# --------------------------------------------------------------------------- #
#                       4.  ОДИН  ПУНКТ  FAQ                                 #
# --------------------------------------------------------------------------- #
def faq_item_kb(role_code: str, qid: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Редактировать", callback_data=f"faq_edit:{role_code}:{qid}")
    kb.button(text="🗑 Удалить", callback_data=f"faq_del:{role_code}:{qid}")
    kb.button(text="Назад", callback_data=f"faq_list:{role_code}:0")
    return kb.adjust(1).as_markup()


def confirm_edit_kb(role_code: str, qid: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Сохранить", callback_data=f"faq_update:{role_code}:{qid}")
    kb.button(text="Назад", callback_data=f"faq_edit_cancel:{role_code}:{qid}")
    return kb.adjust(1).as_markup()


# --------------------------------------------------------------------------- #
#                         5.  CONFIRM  «ГОТОВО/НАЗАД»                         #
# --------------------------------------------------------------------------- #
def confirm_kb(role_code: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Готово", callback_data=f"faq_save:{role_code}")
    kb.button(text="Назад", callback_data=f"faq_role_back:{role_code}")
    return kb.adjust(1).as_markup()
