"""
Aiogram-фильтр: проверяет,
  – есть ли у пользователя роль, начинающаяся с «admin», **или**
  – пришёл ли апдейт из служебного чата заявок на регистрацию.
"""

from __future__ import annotations

from typing import Final

from aiogram import types
from aiogram.filters import BaseFilter

from db.database import get_user_role
from config import request_bot_user_chat_id       # ⬅ добавили

_ADMIN_PREFIX: Final = "admin"    # admin, admin_readonly, admin_test и т. п.


class IsAdmin(BaseFilter):
    """
    Срабатывает для Message- и CallbackQuery-хэндлеров, если выполнено
    одно из условий:
      • у пользователя есть роль, начинающаяся с «admin»;
      • апдейт пришёл из чата `request_bot_user_chat_id`
        (кнопки в чате рассмотрения заявок).
    """

    __slots__ = ()

    async def __call__(self, event: types.Message | types.CallbackQuery) -> bool:  # type: ignore[override]
        # 👉 1. Разрешаем всё, что приходит из чата рассмотрения заявок
        chat_id: int | None = None
        if isinstance(event, types.Message):
            chat_id = event.chat.id
        elif isinstance(event, types.CallbackQuery) and event.message:
            chat_id = event.message.chat.id

        if chat_id == request_bot_user_chat_id:
            return True

        # 👉 2. Иначе проверяем роль пользователя
        role: str | None = get_user_role(event.from_user.id)
        return (role or "").startswith(_ADMIN_PREFIX)
