"""
FSM-состояния блока «Управление пользователями / администраторами».
"""

from aiogram.fsm.state import State, StatesGroup


class SupAdmUserManage(StatesGroup):
    AwaitUserSearch = State()   # ждём inline-выбора
    AwaitAction = State()       # выбрана карточка, ждём действий
