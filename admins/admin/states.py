"""
FSM-состояния модуля «admin».
"""

from aiogram.fsm.state import State, StatesGroup


class AskSAForm(StatesGroup):
    """Администратор формулирует вопрос суперадминам."""
    WaitingForQuestion = State()


class SAReplyForm(StatesGroup):
    """Суперадмин набирает текст ответа."""
    WaitingForReplyText = State()


class AParticipantSearch(StatesGroup):
    """Админ ищет участницу по ФИО через inline-query."""
    WaitingInline = State()
