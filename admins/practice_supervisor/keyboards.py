"""
Inline-клавиатуры для модуля «Practice Supervisor».
"""

from __future__ import annotations

from typing import Dict, List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

FAQ_PER_PAGE: int = 7  # вопросов на странице


# --------------------------------------------------------------------------- #
#                                 1. FAQ                                      #
# --------------------------------------------------------------------------- #


def _build_faq_page_kb(faq: List[Dict], page: int) -> InlineKeyboardMarkup:
    """
    Формирует клавиатуру одной страницы FAQ.

    *faq* — список словарей c ``id`` / ``question``.  
    *page* — номер страницы (0-based).
    """
    total_pages = max(1, (len(faq) - 1) // FAQ_PER_PAGE + 1)
    start, end = page * FAQ_PER_PAGE, (page + 1) * FAQ_PER_PAGE
    page_items = faq[start:end]

    kb = InlineKeyboardBuilder()

    # список вопросов
    for item in page_items:
        kb.button(text=item["question"][:40], callback_data=f"pfaq_q:{item['id']}:{page}")
    kb.adjust(1)

    # навигация «◀️ 1/10 ▶️»
    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀️", callback_data=f"pfaq_page:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="▶️", callback_data=f"pfaq_page:{page + 1}"))
        kb.row(*nav)

    # назад в меню
    kb.row(InlineKeyboardButton(text="🏠 В меню", callback_data="p_menu"))
    return kb.as_markup()


# --------------------------------------------------------------------------- #
#                                 2. Прочее                                   #
# --------------------------------------------------------------------------- #


def back_to_menu_p_kb() -> InlineKeyboardMarkup:
    """Однокнопочная «🏠 В меню»."""
    return InlineKeyboardBuilder().button(text="🏠 В меню", callback_data="p_menu").as_markup()


def scale_kb(step: str, payload: str) -> InlineKeyboardMarkup:
    """
    Шкала 1–3 для ЗКА / ЗКО.

    *step* — префикс callback (``pfb_zka`` или ``pfb_zko``)  
    *payload* — данные, которые нужно сохранить после двоеточия
    """
    kb = InlineKeyboardBuilder()
    for v in (1, 2, 3):
        kb.button(text=str(v), callback_data=f"{step}:{payload}:{v}")
    kb.button(text="🔙 Назад", callback_data=f"{step}_back:{payload}")
    return kb.adjust(3).as_markup()


def absence_kb(payload: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора пропусков."""
    kb = InlineKeyboardBuilder()
    kb.button(text="Более 4 пропусков в месяц", callback_data=f"pfb_abs:{payload}:>4")
    kb.button(text="Менее 4 пропусков в месяц", callback_data=f"pfb_abs:{payload}:<4")
    kb.button(text="Пропуски исключительно по уважительной причине", callback_data=f"pfb_abs:{payload}:minimum")
    kb.button(text="Не пропускает", callback_data=f"pfb_abs:{payload}:0")
    kb.button(text="🔙 Назад", callback_data="pfb_back_zko")
    return kb.adjust(1).as_markup()


def back_from_fb_kb(payload: str) -> InlineKeyboardMarkup:
    """Кнопка «🔙 Назад» с возвратом к оценке ЗКО."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=f"pfb_back_fb:{payload}")]]
    )


def back_menu_p_kb() -> InlineKeyboardMarkup:
    """Финальная кнопка после сохранения ОС."""
    return InlineKeyboardBuilder().button(text="🏠 В меню", callback_data="p_menu").as_markup()
