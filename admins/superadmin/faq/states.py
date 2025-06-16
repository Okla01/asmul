"""
FSM-состояния редактора FAQ.
"""

from aiogram.fsm.state import State, StatesGroup


class FaqStates(StatesGroup):
    SelectRole = State()
    RoleMenu = State()

    # создание
    CreateQ = State()
    CreateA = State()
    ConfirmCreate = State()

    # редактирование
    EditQ = State()
    EditA = State()
    ConfirmEdit = State()

    # импорт Excel
    UploadExcel = State()
