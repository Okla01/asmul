"""
states_commented.py  — описание конечных автоматов состояний (FSM)
для сценария фиксации нарушения участницы.

Файл содержит две группы состояний:

1. `VioFSM`   — основной сценарий (поиск → карточка → описание → дата → файл → …).
2. `ViolCal`  — вспомогательный FSM для диалога календаря (один шаг выбора даты).
"""

from aiogram.fsm.state import StatesGroup, State


# ────────────────────────────────────────────────────────────────────────────────
class VioFSM(StatesGroup):
    """
    Сценарий фиксации нарушения.

    Диаграмма переходов (упрощённо)
    -------------------------------
        FindUser ──▶ CardFull ──▶ ChooseSeverity ──▶ ChooseTemplate
                     ▲  │                            │
                     │  └───── CardShort ◀───────────┘
                     │
                     └───────── (vio_back) ─────────▶ [выход]

        ChooseTemplate ──▶ CustomDescr ──▶ ChooseDate
                               │                │
                               └───────────────┘

        ChooseDate ──▶ WaitingFile ──▶ Confirm ──▶ (vio_save) ──▶ [выход]
    """
    FindUser = State()         # Поиск участницы (inline_mode)
    CardShort = State()        # Короткая карточка (с выбором цикла)
    CardFull = State()         # Полная карточка (кнопка «Выставить нарушение»)
    ChooseSeverity = State()   # Выбор тяжести
    ChooseTemplate = State()   # Выбор типового шаблона
    CustomDescr = State()      # Пользовательский ввод описания
    ChooseDate = State()       # Выбор даты (кнопки / календарь)
    WaitingFile = State()      # Ожидание файла‑подтверждения
    Confirm = State()          # Итоговое подтверждение перед записью


# ────────────────────────────────────────────────────────────────────────────────
class ViolCal(StatesGroup):
    """
    Вспомогательный FSM для диалога календаря.
    Один‑единственный шаг `Pick` — выбор даты.
    """
    Pick = State()
