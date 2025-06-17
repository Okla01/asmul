from aiogram.fsm.state import State, StatesGroup

class AdminRegistration(StatesGroup):
    WaitingForFIO = State()
    WaitingForApproval = State()
