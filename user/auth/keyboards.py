from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder



stage_1_1_kb = InlineKeyboardBuilder()
stage_1_1_kb.button(text="Назад", callback_data="back_1_1")
stage_1_1_kb = stage_1_1_kb.as_markup()

user_main_menu_kb = InlineKeyboardBuilder()
user_main_menu_kb.button(text="Информация обо мне", callback_data="user_main_myinfo")
user_main_menu_kb.button(text="Отчет чистоты", callback_data="user_main_cleanreport")
user_main_menu_kb.button(text="Отчет с мероприятия", callback_data="user_main_eventreport")
user_main_menu_kb.button(text="Отметка об отсутствии", callback_data="user_main_absence")
user_main_menu_kb.button(text="FAQ (ЧЗВ)", callback_data="user_main_faq")
user_main_menu_kb = user_main_menu_kb.adjust(1).as_markup()


async def get_faq_for_user(faq_data):
    if not faq_data:
        raise ValueError("FAQ is empty")
    kb_builder = InlineKeyboardBuilder()
    for item in faq_data:
        q_id = item["id"]
        q_title = item["question"][:40]
        kb_builder.button(
            text=q_title,
            callback_data=f"faq_select_{q_id}"
        )
    kb_builder.button(
        text="Задать вопрос",
        callback_data="ask_admin_question"
    )
    kb_builder.button(
        text="Назад",
        callback_data="user_main_menu"
    )
    return kb_builder.adjust(1).as_markup()


faq_menu_kb = InlineKeyboardBuilder()
faq_menu_kb.button(text="Вернуться к FAQ", callback_data="user_main_faq")
faq_menu_kb.button(text="Вернуться в меню", callback_data="user_main_menu")
faq_menu_kb = faq_menu_kb.adjust(1, 1).as_markup()


async def get_events_keyboard(events) -> InlineKeyboardMarkup:
    """
    Генерирует inline-клавиатуру со списком доступных мероприятий из БД `events`.
    Каждый пункт имеет callback_data вида: eventreport_choose_{event_id}
    """
    buttons = InlineKeyboardBuilder()
    for ev in events:
        buttons.button(text=ev["title"], callback_data=f"eventreport_choose_{ev['id']}")
    # Добавим «Назад» на всякий случай
    buttons.button(text="Назад", callback_data="eventreport_cancel")
    return buttons.adjust(1).as_markup()


reports_event_kb = InlineKeyboardBuilder()
reports_event_kb.button(text="Отправить отчёт", callback_data="eventreport_confirm")
reports_event_kb.button(text="Назад", callback_data="eventreport_back")
reports_event_kb = reports_event_kb.adjust(1, 1).as_markup()


async def get_event_grade_keyboard(attendance_id: int):
    admin_kb = InlineKeyboardBuilder()
    admin_kb.button(text="Подтвердить", callback_data=f"adm_approve_event_{attendance_id}"),
    admin_kb.button(text="Отклонить", callback_data=f"adm_reject_event_{attendance_id}")
    admin_kb = admin_kb.adjust(1, 1).as_markup()
    return admin_kb


back_to_choose_event_kb = InlineKeyboardBuilder()
back_to_choose_event_kb.button(text="Назад", callback_data="user_main_eventreport")
back_to_choose_event_kb = back_to_choose_event_kb.as_markup()

back_to_menu_kb = InlineKeyboardBuilder()
back_to_menu_kb.button(text="Вернуться в меню", callback_data="user_main_menu")
back_to_menu_kb = back_to_menu_kb.as_markup()


def get_admin_reply_kb(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✍️ Ответить пользователю",
        callback_data=f"admin_reply_us_{user_id}"
    )
    return builder.as_markup()


# --- Константы для Отсутствия ---
LOC_CALLBACK_PREFIX = "absence_loc_"  # места отсутствия
REASON_CALLBACK_PREFIX = "absence_reason_"  # причины отсутствия
CONFIRM_REASON_CALLBACK = "absence_confirm_reason"
SKIP_COMMENT_CALLBACK = "absence_skip_comment"
BACK_CALLBACK = "absence_back"  # общий «Назад»
NEXT_FILE_STAGE = "absence_next_file"
SUBMIT_CALLBACK = "absence_submit"  # финальное «Утвердить»
APPROVE_REASON_CALLBACK = "absence_approve_reason"
EDIT_REASON_CALLBACK = "absence_edit_reason"
UPLOAD_FILE_CB = "absence_upload_file"


async def get_location_keyboard(selected: list[str] | None = None) -> InlineKeyboardMarkup:
    selected = selected or []
    opts = {"Работа": "work",
            "Лекции": "lectures",
            "Русский язык": "russian_lang",
            "Мероприятия": "events",
            "Интеграционная программа": "foreign_lang",
            }
    kb = InlineKeyboardBuilder()
    for caption, val in opts.items():
        prefix = "✅ " if val in selected else ""
        kb.button(text=prefix + caption, callback_data=LOC_CALLBACK_PREFIX + val)
    kb.button(text="Назад",  callback_data="user_main_menu")
    kb.button(text="Далее", callback_data=CONFIRM_REASON_CALLBACK)
    return kb.adjust(2, 2, 1, 2).as_markup()


async def get_reason_keyboard(selected: str | None = None) -> InlineKeyboardMarkup:
    opts = {"Болезнь": "illness",
            "Отпуск": "vacation",
            "Семейные обстоятельства": "family",
            "Другое": "other"}
    kb = InlineKeyboardBuilder()
    for caption, val in opts.items():
        prefix = "✅ " if val == selected else ""
        kb.button(text=prefix + caption, callback_data=REASON_CALLBACK_PREFIX + val)
    kb.button(text="Назад", callback_data=BACK_CALLBACK)
    kb.button(text="Подтвердить", callback_data=CONFIRM_REASON_CALLBACK)
    return kb.adjust(2, 1, 1, 2).as_markup()


def get_file_step_kb(mandatory: bool, current_count: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Назад", callback_data=BACK_CALLBACK)
    # кнопка «Далее» доступна, если файл необязательный или уже есть хоть один прикреплённый
    if not mandatory or current_count > 0:
        kb.button(text="Далее", callback_data=NEXT_FILE_STAGE)
    return kb.adjust(2).as_markup()


def get_absence_admin_kb(absence_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="Согласовать", callback_data=f"absence_ok_{absence_id}")
    kb.button(text="Отклонить",   callback_data=f"absence_reject_{absence_id}")
    return kb.adjust(1, 1).as_markup()


delete_this_msg_kb = InlineKeyboardBuilder()
delete_this_msg_kb.button(text='Закрыть', callback_data='delete_this_msg')
delete_this_msg_kb = delete_this_msg_kb.as_markup()


logout_from_account_user_kb = InlineKeyboardBuilder()
logout_from_account_user_kb.button(text='Да', callback_data='user_main_logout')
logout_from_account_user_kb.button(text='Отмена', callback_data='user_main_menu')
logout_from_account_user_kb = logout_from_account_user_kb.as_markup()
