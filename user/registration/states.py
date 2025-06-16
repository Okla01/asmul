from aiogram.fsm.state import State, StatesGroup


class RegistrationForm(StatesGroup):
    WaitForFIO = State()
    WaitForGender = State()
    WaitForCountry = State()
    WaitForPhone = State()
    WaitForEmail = State()
    WaitForAge = State()
    WaitForConfirm = State()

    WaitForPhoto = State()  # Stage 2.1
    WaitForPassportChoice = State()  # Stage 2.2 (выбираем есть/нет паспорта)
    WaitForPassportReason = State()  # Stage 2.2.1 (причина отсутствия)
    WaitForPassportAttach = State()  # Stage 2.2.2 (загрузка паспорта)
    WaitForFinalConfirm = State()  # После фото/паспорта — финальная сводка

    WaitForASMIR = State()
    WaitForVSMIR = State()


class AskQuestionForm(StatesGroup):
    WaitingForQuestion = State()  # пользователь печатает вопрос
    WaitingForQuestionForLLM = State()  # пользователь печатает вопрос


class AdminReplyFormCand(StatesGroup):
    WaitingForReplyText = State()
