"""
Aiogram-фильтр: пропускает апдейт **только** от разрешённых user_id.

Использование:
    @dp.message(AllowedIDs())                # берёт список из config.ADMIN_COMMAND_IDS
    @dp.message(AllowedIDs({123, 456}))      # передаём набор ID вручную
"""

from __future__ import annotations

from typing import Iterable, Set

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from config import ADMIN_COMMAND_IDS


class AllowedIDs(BaseFilter):
    """
    Parameters
    ----------
    ids
        Iterable с разрешёнными ID. Если не указан, используется
        набор `ADMIN_COMMAND_IDS` из конфигурации.
    """

    __slots__ = ("_ids",)

    def __init__(self, ids: Iterable[int] | None = None) -> None:
        # Приводим к множеству (O(1) lookup) и одновременно убираем дубли.
        self._ids: Set[int] = set(ids) if ids is not None else set(ADMIN_COMMAND_IDS)

    async def __call__(self, event: Message | CallbackQuery) -> bool:  # type: ignore[override]
        """Aiogram вызывает этот метод, чтобы решить, пускать ли апдейт в хэндлер."""
        return event.from_user.id in self._ids
