"""
FSM-состояния «Экспорт отчётов / статистика».
"""

from aiogram.fsm.state import State, StatesGroup


class RepFSM(StatesGroup):
    Main = State()            # первое меню

    # статистика
    StatsShow = State()

    # «Отсутствия» — выбор объектов
    ChooseAbsObj = State()

    # универсальный экспорт
    ChooseStart = State()
    ChooseEnd = State()
    ChooseFormat = State()

    # служебное состояние для диалога-календаря
    # (aiogram_dialog создаёт свою FSM, но мы держим ссылки здесь)
    Done = State()
