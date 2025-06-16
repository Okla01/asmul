"""
FSM-состояния модуля «Рассылки».
"""

from aiogram.fsm.state import State, StatesGroup


class Mailing(StatesGroup):
    # базовый сценарий
    ChooseTarget = State()
    ChooseTik = State()
    ChooseStaff = State()
    WriteText = State()
    Confirm = State()
    SetSchedule = State()
    SetRecurrence = State()

    # список / детали
    ViewPlanned = State()
    PlannedDetail = State()

    # редактирование
    EditMenu = State()
    EditText = State()
    EditSchedule = State()
    EditRecurrence = State()
    DeleteConfirm = State()
