"""
FSM-состояния модуля «Practice Supervisor».
"""

from aiogram.fsm.state import State, StatesGroup


class PracticeFeedback(StatesGroup):
    """Многошаговая форма обратной связи (ОС)."""
    WaitingInline = State()    # выбор участницы (inline-поиск)
    WaitZka = State()          # оценка ЗКА
    WaitZko = State()          # оценка ЗКО
    WaitFb = State()           # ввод SMART-feedback
    WaitAbsence = State()      # выбор пропусков


class PSParticipantSearch(StatesGroup):
    """Простое отображение карточки участницы (без обратной связи)."""
    WaitingInline = State()
