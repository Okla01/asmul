"""
Inline-клавиатуры для переключения флага `os_enabled`.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def os_toggle_kb(enabled: bool) -> InlineKeyboardMarkup:
    """
    Два варианта:
    • если *enabled* = True  → кнопка «🔴 Выключить»;
    • если *enabled* = False → кнопка «🟢 Включить».

    Всегда добавляется кнопка «🔙 Вернуться в меню».
    """
    kb = InlineKeyboardBuilder()

    if enabled:
        kb.button(text="🔴 Выключить", callback_data="sa_os_off")
    else:
        kb.button(text="🟢 Включить", callback_data="sa_os_on")

    kb.button(text="🔙 Вернуться в меню", callback_data="sa_menu")
    return kb.adjust(1).as_markup()
