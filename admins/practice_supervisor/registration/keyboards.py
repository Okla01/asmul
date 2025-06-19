"""
Inline-клавиатуры для регистрации руководителя практики.
"""

from __future__ import annotations

from typing import List, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.database import get_all_departments, get_modules_by_department


def get_ps_register_kb() -> InlineKeyboardMarkup:
    """Одна кнопка «🔐 Зарегистрироваться как руководитель практики»."""
    return (
        InlineKeyboardBuilder()
        .button(
            text="🔐 Зарегистрироваться как руководитель практики",
            callback_data="ps_register",
        )
        .as_markup()
    )


# def get_ps_request_approval_kb(request_id: int) -> InlineKeyboardMarkup:
#     """Кнопки для админов: «Разрешить» / «Отклонить»."""
#     return (
#         InlineKeyboardBuilder()
#         .button(text="✅ Разрешить доступ", callback_data=f"ps_approve:{request_id}")
#         .button(text="🚫 Отклонить", callback_data=f"ps_reject:{request_id}")
#         .adjust(2)
#         .as_markup()
#     )
    
def get_ps_request_approval_kb(request_id: int) -> InlineKeyboardMarkup:
    """
    Кнопки под заявкой РП в админ-чате: «Одобрить» / «Отклонить».

    callback_data:
        • ps_approve:{request_id}
        • ps_reject:{request_id}
    """
    return (
        InlineKeyboardBuilder()
        .button(text="✅ Одобрить",  callback_data=f"ps_approve:{request_id}")
        .button(text="🚫 Отклонить", callback_data=f"ps_reject:{request_id}")
        .adjust(2)
        .as_markup()
    )



def get_departments_kb(
    *,
    callback_prefix: str = "ps_dept",
    include_back: bool = False,
    back_callback: str = "ps_back",
) -> InlineKeyboardMarkup:
    """
    Список всех подразделений из БД.

    callback_data: ``{callback_prefix}:{department_encoded}``
                   (':' → '_' для безопасности).
    """
    kb = InlineKeyboardBuilder()
    for dept in get_all_departments():
        encoded = dept.replace(":", "_")
        kb.button(text=dept, callback_data=f"{callback_prefix}:{encoded}")
    if include_back:
        kb.button(text="🔙 Назад", callback_data=back_callback)
    return kb.adjust(1).as_markup()


def get_modules_kb_for_rp(
    *,
    department: str,
    req_id: int,
    callback_prefix: str = "ps_rp_module",
    include_back: bool = True,
    back_callback: str = "ps_module_back",
) -> InlineKeyboardMarkup:
    """
    Список модулей выбранного подразделения для РП после одобрения заявки.

    callback_data: ``{callback_prefix}:{req_id}:{module_encoded}``
    """
    kb = InlineKeyboardBuilder()
    for mod in get_modules_by_department(department):
        encoded = mod.replace(":", "_")
        kb.button(text=mod, callback_data=f"{callback_prefix}:{req_id}:{encoded}")
    if include_back:
        kb.button(text="🔙 Отмена", callback_data=back_callback)
    return kb.adjust(1).as_markup()
