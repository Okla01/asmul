"""
FSM-состояния блока «Events».
"""

from aiogram.fsm.state import State, StatesGroup


class EventFSM(StatesGroup):
    # главное меню
    SelectAction = State()

    # создание
    CreateTitle = State()
    CreateDesc = State()
    CreateDate = State()
    ConfirmCreate = State()

    # списки и просмотр
    ListEvents = State()
    EventMenu = State()

    # редактирование
    EditTitle = State()
    EditDesc = State()
    EditDate = State()

    # служебные
    ConfirmDelete = State()
