"""
calendar_commented.py  — диалог выбора даты нарушения участницы.

Модуль использует aiogram‑dialog (виджет `Calendar`) для показа inline‑календаря.
Результат выбранной пользователем даты передаётся «наружу» в FSM родительского
хендлера через объект `FSMContext`, который мы кладём в `DialogManager.start_data`
при открытии диалога.

Основная точка входа — объект `viol_calendar_dialog`, который содержит одно окно
(`Window`) с календарём. После выбора даты вызывается колбэк‐функция `on_pick`.
"""

from datetime import date
from aiogram.types import CallbackQuery
from aiogram_dialog import Dialog, Window, DialogManager
from aiogram_dialog.widgets.kbd import Calendar
from aiogram_dialog.widgets.text import Const

# --- внутренние импорты проекта ---
from admins.superadmin.violations.states import ViolCal
from aiogram.fsm.context import FSMContext


# ────────────────────────────────────────────────────────────────────────────────
# CALLBACK: пользователь выбрал дату
# ────────────────────────────────────────────────────────────────────────────────
async def on_pick(
        c: CallbackQuery,
        widget: Calendar,
        manager: DialogManager,
        d: date) -> None:
    """
    Вызывается автоматически, когда пользователь нажимает на день в календаре.

    Параметры
    ---------
    c : CallbackQuery
        Исходный callback‑апдейт от Telegram.
    widget : Calendar
        Экземпляр календаря, который сгенерировал событие (не используем).
    manager : DialogManager
        Объект‑менеджер диалога, предоставляет доступ к данным диалога и методам
        управления стэком окон.
    d : date
        Выбранная пользователем дата.

    Действия
    --------
    1. Получаем внешний FSM через `manager.start_data` (он был передан при
       открытии календаря).
    2. Сохраняем строковое представление даты в контексте внешнего FSM.
    3. Закрываем диалог календаря (`manager.done()`).
    4. Возвращаем управление родительскому хендлеру — вызываем `_ask_file`,
       чтобы показать следующий шаг («прикрепите файл‑подтверждение»).
    """
    # внешний FSM передаём через data
    vio_fsm: FSMContext = manager.start_data["parent_fsm"]

    # сохраняем дату в формате dd.mm.yyyy
    await vio_fsm.update_data(vdate=d.strftime("%d.%m.%Y"))

    # импорт внутри функции, чтобы не возник циклическая зависимость при импорте
    from admins.superadmin.violations.handlers import _ask_file

    # закрываем диалог календаря (возврат к родительскому сообщению)
    await manager.done()

    # выводим следующий шаг
    await _ask_file(c, vio_fsm)


# ────────────────────────────────────────────────────────────────────────────────
# ОКНО ДИАЛОГА
# ────────────────────────────────────────────────────────────────────────────────
# Одно окно: текст‑заголовок + сам календарь.
win = Window(
    Const("🗓 Выберите <b>дату нарушения</b>:"),      # статический текст
    Calendar(id="viol_cal", on_click=on_pick),       # виджет‑календарь
    state=ViolCal.Pick,                              # состояние FSM‑группы
    parse_mode="HTML"
)

# Объект, который будет запускаться из внешнего хендлера
viol_calendar_dialog = Dialog(win)
