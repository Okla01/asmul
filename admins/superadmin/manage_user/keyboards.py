"""
Inline-клавиатуры для управления пользователями и администраторами.
"""

from __future__ import annotations

from typing import Set

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ROLES

# --------------------------------------------------------------------------- #
#                      1. КНОПКА «🔍 Найти …»                                 #
# --------------------------------------------------------------------------- #
def sa_manage_entry_kb(label: str) -> InlineKeyboardMarkup:
    """
    `label` — родительный падеж («администратора» / «пользователя»).
    """
    return (
        InlineKeyboardBuilder()
        .button(text=f"🔍 Найти {label}", switch_inline_query_current_chat="su: ")
        .button(text="🔙 В меню", callback_data="sa_main_menu")
        .adjust(1)
        .as_markup()
    )


# --------------------------------------------------------------------------- #
#                    2.  КЛАВИАТУРА КАРТОЧКИ ПОЛЬЗОВАТЕЛЯ                    #
# --------------------------------------------------------------------------- #
def sa_user_kb(
    user_id: int,
    current_role: str,
    blocked: bool,
    mode: str,
) -> InlineKeyboardMarkup:
    """
    • `mode = "admins"` — показ только admin_* (кроме суперадмина).  
    • `mode = "users"`  — показ только не-admin ролей.  
    """
    kb = InlineKeyboardBuilder()

    def _allowed(code: str) -> bool:
        if mode == "admins":
            return code.startswith("admin_") and code != "admin_supervisor"
        return not code.startswith("admin_")

    # — роли —
    for code, title in ROLES.items():
        if not _allowed(code):
            continue
        prefix = "✅ " if code == current_role else ""
        kb.button(text=f"{prefix}{title}", callback_data=f"sa_setrole:{user_id}:{code}")

    # — блок / разблок —
    if mode == "users":
        if blocked:
            kb.button(text="✅ Разблокировать", callback_data=f"sa_unblock:{user_id}")
        else:
            kb.button(text="🚫 Заблокировать", callback_data=f"sa_block:{user_id}")

    kb.button(text="🔙 В меню", callback_data="sa_main_menu")
    kb.adjust(1)
    return kb.as_markup()
