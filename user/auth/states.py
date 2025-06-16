from aiogram.fsm.state import State, StatesGroup


class AuthForm(StatesGroup):
    WaitForFIO = State()


class CleanReportStates(StatesGroup):
    WaitingPhotos = State()  # Когда пользователь загружает 7 фото
    AdminWaitingRate = State()  # Когда админ выбирает «Чисто», «Удовлетворительно», «Грязно»
    AdminWaitingComment = State()


class EventReportStates(StatesGroup):
    ChoosingEvent = State()  # Пользователь выбирает мероприятие
    WaitingForPhoto = State()  # Ожидаем фото (или иной материал) для отчёта
    Confirming = State()


class AbsenceCal(StatesGroup):
    Start = State()
    End = State()


class AdminAbsence(StatesGroup):
    WaitingComment = State()     # ждём причину отклонения


class AbsenceFlow(StatesGroup):
    ChoosingLocation = State()  # 4.1.2.5
    ChoosingReason = State()  # 4.1.2.5/1
    WaitingForOther = State()  # 4.1.2.5/1/4 – ввод «Другое»
    DocumentUpload = State()  # 4.1.2.5/1.x
    WaitingForComment = State()  # 4.1.2.5/2   (доп. комментарий)
    ConfirmingReason = State()  # 4.1.2.5/2.1 «Причина заполнена!»
    ConfirmingDetails = State()  # 4.1.2.5/2.4


class UserInfoStates(StatesGroup):
    WaitingForFullName = State()
    ShowingInfo = State()


class AskAdminForm(StatesGroup):
    WaitingForQuestion = State()


class AdminReplyFormAuth(StatesGroup):
    WaitingForReplyText = State()
