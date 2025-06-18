"""
Клавиатуры для админ-панели (role = admin).
"""

from __future__ import annotations

from typing import Dict, List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

FAQ_PER_PAGE: int = 7  # вопросов на страницу


# --------------------------------------------------------------------------- #
#                              1. FAQ                                         #
# --------------------------------------------------------------------------- #


def build_faq_page_kb(faq: List[Dict], page: int) -> InlineKeyboardMarkup:
    """
    Формирует клавиатуру для одной страницы FAQ.

    *faq* — список словарей с ключами ``id`` и ``question``.  
    *page* — номер страницы (0-based).
    """
    total_pages: int = max(1, (len(faq) - 1) // FAQ_PER_PAGE + 1)
    start, end = page * FAQ_PER_PAGE, (page + 1) * FAQ_PER_PAGE
    page_items = faq[start:end]

    kb = InlineKeyboardBuilder()

    # ───── список вопросов (в один столбец) ─────
    for item in page_items:
        q_id: int = item["id"]
        title: str = item["question"][:40]
        kb.button(text=title, callback_data=f"afaq_q:{q_id}:{page}")
    kb.adjust(1)

    # ───── навигация «◀️ 1/10 ▶️» ─────
    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []

        if page > 0:
            nav.append(
                InlineKeyboardButton(text="◀️", callback_data=f"afaq_page:{page - 1}")
            )

        nav.append(
            InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop")
        )

        if page < total_pages - 1:
            nav.append(
                InlineKeyboardButton(text="▶️", callback_data=f"afaq_page:{page + 1}")
            )

        kb.row(*nav)

    # ───── кнопка «Вернуться в меню» ─────
    kb.row(InlineKeyboardButton(text="🏠 В меню", callback_data="a_menu"))

    return kb.as_markup()


# --------------------------------------------------------------------------- #
#                              2. Разное                                      #
# --------------------------------------------------------------------------- #


def back_to_menu_a_kb() -> InlineKeyboardMarkup:
    """Однокнопочная клавиатура «🏠 В меню» (admin)."""
    return (
        InlineKeyboardBuilder()
        .button(text="🏠 В меню", callback_data="a_menu")
        .as_markup()
    )


def get_sa_reply_kb(admin_id: int) -> InlineKeyboardMarkup:
    """Кнопка «✉️ Ответить» под вопросом в группе суперадминов."""
    return (
        InlineKeyboardBuilder()
        .button(text="✉️ Ответить", callback_data=f"sa_reply_{admin_id}")
        .as_markup()
    )