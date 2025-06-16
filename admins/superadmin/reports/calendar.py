"""
Диалог-календарь для выбора дат отчёта.

Используется два раза:
* шаг «start»  – начальная дата;
* шаг «end»    – конечная дата.

Дата, выбранная пользователем, сохраняется прямо в FSM-контексте
(`RepFSM.ChooseStart` / `RepFSM.ChooseEnd`) под ключами ``start`` / ``end``.
"""

from __future__ import annotations

from datetime import date

from aiogram.types import CallbackQuery
from aiogram_dialog import Dialog, DialogManager, Window
from aiogram_dialog.widgets.kbd import Calendar
from aiogram_dialog.widgets.text import Const

from admins.superadmin.reports.states import RepFSM

# --------------------------------------------------------------------------- #
#                                HANDLER                                      #
# --------------------------------------------------------------------------- #


async def on_pick(
    c: CallbackQuery,
    widget: Calendar,
    mgr: DialogManager,
    d: date,
) -> None:
    """
    Callback календаря.

    ➊ Берём параметр ``step`` из `mgr.start_data` (он равен `"start"` или `"end"`).
    ➋ Записываем выбранную дату в FSM (`RepFSM`) через `update_data`.
    ➌ Вызываем `back_from_calendar` из родительского модуля, чтобы продолжить
       цепочку шагов.
    """
    step: str = mgr.start_data["step"]            # ← раньше было mgr.dialog_data
    await mgr.start_data["fsm"].update_data(**{step: d.strftime("%d.%m.%Y")})

    from admins.superadmin.reports.handlers import back_from_calendar
    await back_from_calendar(c, mgr)              # вернуть управление
    await mgr.done()


# --------------------------------------------------------------------------- #
#                               WINDOWS                                       #
# --------------------------------------------------------------------------- #

_CHOOSE_TXT = Const("🗓 Выберите дату:")

win_start = Window(_CHOOSE_TXT, Calendar(id="rep_cal_start", on_click=on_pick),
                   state=RepFSM.ChooseStart, parse_mode="HTML")

win_end = Window(_CHOOSE_TXT, Calendar(id="rep_cal_end", on_click=on_pick),
                 state=RepFSM.ChooseEnd, parse_mode="HTML")

rep_calendar_dialog = Dialog(win_start, win_end)
