"""
FSM-состояния для регистрации руководителя практики.
"""

from aiogram.fsm.state import State, StatesGroup


class PSRegister(StatesGroup):
    """Первичная форма регистрации РП."""
    WaitingFullName = State()
    WaitingDepartment = State()
    WaitingModule = State()

class PSModuleAfterApprove(StatesGroup):
    """Выбор модуля после одобрения заявки."""
    WaitingModule = State()
