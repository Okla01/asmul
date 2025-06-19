"""
Фильтр «IsAdmin».

Срабатывает, если:
  • у пользователя есть роль, начинающаяся с «admin», ИЛИ
  • апдейт пришёл из служебного чата заявок на регистрацию
    (кнопки «Одобрить / Отклонить»).
"""

from __future__ import annotations

from typing import Final

from aiogram import types
from aiogram.filters import BaseFilter

from db.database import get_user_role
from config import request_bot_user_chat_id    # id чата рассмотрения заявок

_ADMIN_PREFIX: Final = "admin"    # admin*, admin_readonly, admin_practice_supervisor ...


class IsAdmin(BaseFilter):
    """Фильтр для Message и CallbackQuery."""

    __slots__ = ()

    async def __call__(self, event: types.Message | types.CallbackQuery) -> bool:  # type: ignore[override]
        # 1. Разрешаем всё, что приходит из чата рассмотрения заявок
        chat_id: int | None = None
        if isinstance(event, types.Message):
            chat_id = event.chat.id
        elif isinstance(event, types.CallbackQuery) and event.message:
            chat_id = event.message.chat.id

        if chat_id == request_bot_user_chat_id:
            return True

        # 2. Проверяем роль пользователя
        role: str | None = get_user_role(event.from_user.id)
        return (role or "").startswith(_ADMIN_PREFIX)
