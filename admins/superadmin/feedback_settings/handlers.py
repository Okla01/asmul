"""
Переключатель возможности оставлять ОС (обратную связь)
руководителям практики.

Только суперадмин («admin_supervisor») может:
* увидеть текущее состояние флага `os_enabled`;
* включить / выключить его.

Клавиатуры см. в `keyboards.py`.
"""

from __future__ import annotations

from typing import Final

from aiogram import F, types
from aiogram.exceptions import TelegramBadRequest

from admins.filters.is_admin import IsAdmin
from admins.superadmin.feedback_settings.keyboards import os_toggle_kb
from config import dp
from db.database import get_bool_setting, get_user_role, set_bool_setting

_SUPERVISOR_ROLE: Final = "admin_supervisor"
_FLAG_KEY: Final = "os_enabled"


# ─────────────────────────── корневое меню ──────────────────────────────── #
@dp.callback_query(F.data == "sa_os_view", IsAdmin())
async def sa_os_menu(cb: types.CallbackQuery) -> None:
    """
    Отображает текущее состояние опции «Оставлять ОС» и кнопки включения/выключения.
    """
    if get_user_role(cb.from_user.id) != _SUPERVISOR_ROLE:
        return await cb.answer("Доступно только суперадмину.", show_alert=True)

    enabled: bool = get_bool_setting(_FLAG_KEY, False)
    status = "включено ✅" if enabled else "выключено 🚫"

    try:
        await cb.message.edit_text(
            "<b>Отображение ОС для руководителей практики</b>\n\n"
            f"Текущий статус: <b>{status}</b>",
            parse_mode="HTML",
            reply_markup=os_toggle_kb(enabled),
        )
    except TelegramBadRequest:
        # fallback — на случай, если исходное сообщение было удалено
        await cb.message.answer(
            "<b>Отображение ОС для руководителей практики</b>\n\n"
            f"Текущий статус: <b>{status}</b>",
            parse_mode="HTML",
            reply_markup=os_toggle_kb(enabled),
        )
    await cb.answer()


# ─────────────────────────── переключатели ──────────────────────────────── #
@dp.callback_query(F.data.in_(("sa_os_on", "sa_os_off")), IsAdmin())
async def sa_os_switch(cb: types.CallbackQuery) -> None:
    """
    Обработчик «🟢 Включить» / «🔴 Выключить».

    * sa_os_on  → turn_on = True
    * sa_os_off → turn_on = False
    """
    if get_user_role(cb.from_user.id) != _SUPERVISOR_ROLE:
        return await cb.answer("Доступно только суперадмину.", show_alert=True)

    turn_on: bool = cb.data == "sa_os_on"
    set_bool_setting(_FLAG_KEY, turn_on)

    status_txt = "включена ✅" if turn_on else "выключена 🚫"
    await cb.message.edit_text(
        f"Возможность дать ОС {status_txt}.",
        parse_mode="HTML",
        reply_markup=os_toggle_kb(turn_on),
    )
    await cb.answer("Сохранено!")
