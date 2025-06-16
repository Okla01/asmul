"""
Aiogram-фильтр: проверяет, что роль пользователя начинается с «admin».
"""

from __future__ import annotations

from typing import Final

from aiogram import types
from aiogram.filters import BaseFilter

from db.database import get_user_role

_ADMIN_PREFIX: Final = "admin"    # admin, admin_readonly, admin_test и т. п.


class IsAdmin(BaseFilter):
    """
    Срабатывает для событий, где `event.from_user.id` принадлежит
    пользователю с ролью, начинающейся на «admin».

    Подходит и для Message-, и для CallbackQuery-хэндлеров.
    """

    __slots__ = ()

    async def __call__(self, event: types.Message | types.CallbackQuery) -> bool:  # type: ignore[override]
        role: str | None = get_user_role(event.from_user.id)
        # None → "" чтобы .startswith() не вызвал AttributeError
        return (role or "").startswith(_ADMIN_PREFIX)
