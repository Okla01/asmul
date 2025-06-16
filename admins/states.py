"""
Определения кратких FSM-машин, которые нужны множеству модулей админки.
"""

from aiogram.fsm.state import State, StatesGroup


class ImportFSM(StatesGroup):
    """Ожидаем файл для замены существующего (используется в /import)."""
    waiting_for_file = State()
