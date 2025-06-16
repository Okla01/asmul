"""
Модуль «Рассылки» (Super-Admin)
===============================

Функциональность
----------------
1. «Кому» — участницы (по тикам) / все / сотрудники (по категориям) / кандидатки.
2. Режим «сейчас» и планирование (дата + периодичность).
3. Просмотр / редактирование / удаление будущих рассылок.
4. Фоновый `scheduler.py` раз в минуту отправляет отложенные сообщения.
"""

from __future__ import annotations

import json
from datetime import datetime
from textwrap import shorten
from typing import Final, Iterable, List, Set

from aiogram import F, html, types
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from admins.filters.is_admin import IsAdmin
from admins.keyboards import delete_this_msg, get_superadmin_panel_kb
from admins.superadmin.mailing.keyboards import (
    STAFF_CATEGORIES,
    confirm_kb,
    edit_opts_kb,
    planned_detail_kb,
    recurrence_kb,
    staff_kb,
    targets_kb,
    tiks_kb,
)
from admins.superadmin.mailing.states import Mailing
from config import bot, dp
from db.database import conn, cursor

# --------------------------------------------------------------------------- #
#                              ВСПОМОГАТЕЛЬНОЕ                                #
# --------------------------------------------------------------------------- #

_REC_HUMAN: Final = {
    "once": "один раз",
    "daily": "каждый день",
    "weekly": "каждую неделю",
    "monthly": "каждый месяц",
}

_REC_CB2CODE: Final = {
    "rec_once": "once",
    "rec_day": "daily",
    "rec_week": "weekly",
    "rec_month": "monthly",
}


def _rec_to_human(code: str) -> str:
    """'daily' → 'каждый день'."""
    return _REC_HUMAN.get(code, code)


def _collect_recipients(filters: dict) -> List[int]:
    """
    Собираем список `user_id` по выбранной аудитории.

    *target*:
        - ml_all
        - ml_candidates
        - ml_participants  (нужен filters.chosen_tiks)
        - ml_staff         (нужен filters.chosen_staff)
    """
    target: str = filters["target"]

    if target == "ml_all":
        cursor.execute("SELECT user_id FROM users")
        return [r[0] for r in cursor.fetchall()]

    if target == "ml_candidates":
        cursor.execute("SELECT user_id FROM users WHERE role = 'user_unauthorized'")
        return [r[0] for r in cursor.fetchall()]

    if target == "ml_participants":
        tiks: Set[str] = set(filters.get("chosen_tiks", []))
        if not tiks:
            return []
        placeholders = ", ".join("?" * len(tiks))
        cursor.execute(
            f"SELECT user_id FROM users "
            f"WHERE role = 'user_participant' AND tik IN ({placeholders})",
            tuple(tiks),
        )
        return [r[0] for r in cursor.fetchall()]

    if target == "ml_staff":
        cats: Set[str] = set(filters.get("chosen_staff", []))
        if not cats:
            return []

        roles: list[str] = []
        if "emp" in cats:
            roles.append("employee")
        if "psup" in cats:
            roles.append("admin_practice_supervisor")
        if "admin" in cats:
            roles.append("admin_admin")
        if "supad" in cats:
            roles.append("admin_supervisor")

        placeholders = ", ".join("?" * len(roles))
        cursor.execute(f"SELECT user_id FROM users WHERE role IN ({placeholders})", tuple(roles))
        return [r[0] for r in cursor.fetchall()]

    return []  # fallback


# --------------------------------------------------------------------------- #
#                      0. ВХОД ИЗ ПАНЕЛИ СУПЕРАДМИНА                          #
# --------------------------------------------------------------------------- #


@dp.callback_query(F.data == "sa_mailing", IsAdmin())
async def ml_entry(cb: types.CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Mailing.ChooseTarget)
    await cb.message.edit_text(
        "Кому вы хотите отправить рассылку?", reply_markup=targets_kb()
    )
    await cb.answer()


# --------------------------------------------------------------------------- #
#                        1. СПИСОК ЗАПЛАНИРОВАННЫХ                            #
# --------------------------------------------------------------------------- #


@dp.callback_query(Mailing.ChooseTarget, F.data == "ml_planned", IsAdmin())
async def ml_show_planned(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Показывает ближайшие 30 будущих рассылок."""
    now_iso = datetime.now().isoformat(timespec="seconds")
    cursor.execute(
        """
        SELECT id, scheduled_at
          FROM mailings
         WHERE scheduled_at > ?
      ORDER BY scheduled_at
         LIMIT 30
        """,
        (now_iso,),
    )
    rows = cursor.fetchall()

    if not rows:
        await cb.message.edit_text(
            "Запланированных рассылок нет.",
            reply_markup=types.InlineKeyboardMarkup(
                inline_keyboard=[[types.InlineKeyboardButton(text="Назад", callback_data="ml_back_targets")]]
            ),
        )
        await cb.answer()
        return

    kb = InlineKeyboardBuilder()
    for mid, iso_dt in rows:
        dt = datetime.fromisoformat(iso_dt).strftime("%d.%m %H:%M")
        kb.button(text=f"{mid} · {dt}", callback_data=f"ml_planned_view:{mid}")
    kb.adjust(1)
    kb.row(types.InlineKeyboardButton(text="Назад", callback_data="ml_back_targets"))

    await state.set_state(Mailing.ViewPlanned)
    await cb.message.edit_text(
        "📋 <b>Запланированные рассылки</b>\nВыберите задачу для деталей:",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )
    await cb.answer()


@dp.callback_query(Mailing.ViewPlanned, F.data.startswith("ml_planned_view:"), IsAdmin())
async def ml_planned_detail(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Подробности конкретной запланированной задачи."""
    mid = int(cb.data.split(":")[1])
    cursor.execute(
        "SELECT scheduled_at, recurrence, message FROM mailings WHERE id = ?", (mid,)
    )
    row = cursor.fetchone()
    if not row:
        return await cb.answer("Не найдено.", show_alert=True)

    sched_iso, rec_code, msg = row
    sched_h = datetime.fromisoformat(sched_iso).strftime("%d.%m.%Y %H:%M")
    preview = shorten(msg, 200, placeholder="…")

    await state.update_data(edit_mid=mid)
    await state.set_state(Mailing.PlannedDetail)
    await cb.message.edit_text(
        f"*ID {mid}*\n"
        f"• Когда: {sched_h}\n"
        f"• Период: {_rec_to_human(rec_code)}\n"
        f"• Текст:\n{preview}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=planned_detail_kb(mid),
    )
    await cb.answer()


# ---------- Удаление ------------------------------------------------------- #


@dp.callback_query(Mailing.PlannedDetail, F.data.startswith("ml_planned_del:"), IsAdmin())
async def ml_del_confirm(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Запрашиваем подтверждение удаления."""
    await state.set_state(Mailing.DeleteConfirm)
    await cb.message.edit_text(
        "❗️ Удалить эту рассылку безвозвратно?",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="Да, удалить", callback_data="ml_del_yes")],
                [types.InlineKeyboardButton(text="Отмена", callback_data="ml_del_no")],
            ]
        ),
    )
    await cb.answer()


@dp.callback_query(Mailing.DeleteConfirm, F.data == "ml_del_yes", IsAdmin())
async def ml_del_yes(cb: types.CallbackQuery, state: FSMContext) -> None:
    mid = (await state.get_data())["edit_mid"]
    cursor.execute("DELETE FROM mailings WHERE id = ?", (mid,))
    conn.commit()

    await state.set_state(Mailing.ViewPlanned)
    await cb.message.edit_text("✅ Удалено.", reply_markup=targets_kb())
    await cb.answer()


@dp.callback_query(Mailing.DeleteConfirm, F.data == "ml_del_no", IsAdmin())
async def ml_del_no(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Возврат к карточке без удаления."""
    mid = (await state.get_data())["edit_mid"]
    cursor.execute(
        "SELECT scheduled_at, recurrence, message FROM mailings WHERE id = ?", (mid,)
    )
    sched_iso, rec_code, msg = cursor.fetchone()
    preview = shorten(msg, 200, placeholder="…")
    await state.set_state(Mailing.PlannedDetail)
    await cb.message.edit_text(
        f"*ID {mid}*\n"
        f"• Когда: {datetime.fromisoformat(sched_iso).strftime('%d.%m.%Y %H:%M')}\n"
        f"• Период: {_rec_to_human(rec_code)}\n\n"
        f"{preview}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=planned_detail_kb(mid),
    )
    await cb.answer()


# ---------- Редактирование ------------------------------------------------- #
# (текст / дата / периодичность)                                             #

@dp.callback_query(Mailing.PlannedDetail, F.data.startswith("ml_planned_edit:"), IsAdmin())
async def ml_edit_menu(cb: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Mailing.EditMenu)
    await cb.message.edit_text("Что изменить?", reply_markup=edit_opts_kb())
    await cb.answer()


# --- Текст ----------------------------------------------------------------- #
@dp.callback_query(Mailing.EditMenu, F.data == "ml_edit_text", IsAdmin())
async def ml_edit_text_start(cb: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Mailing.EditText)
    await cb.message.edit_text("Отправьте новый текст рассылки.\n⬅️ /cancel для возврата.")
    await cb.answer()


@dp.message(Mailing.EditText, IsAdmin())
async def ml_edit_text_save(msg: types.Message, state: FSMContext) -> None:
    mid = (await state.get_data())["edit_mid"]
    cursor.execute("UPDATE mailings SET message = ? WHERE id = ?", (msg.md_text, mid))
    conn.commit()

    await state.set_state(Mailing.PlannedDetail)
    await msg.reply("✅ Текст обновлён.", reply_markup=planned_detail_kb(mid), parse_mode="HTML")


# --- Дата/время ------------------------------------------------------------ #
@dp.callback_query(Mailing.EditMenu, F.data == "ml_edit_dt", IsAdmin())
async def ml_edit_dt_start(cb: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Mailing.EditSchedule)
    await cb.message.edit_text("Новая дата/время (ДД.ММ.ГГГГ ЧЧ:ММ):")
    await cb.answer()


@dp.message(Mailing.EditSchedule, IsAdmin())
async def ml_edit_dt_save(msg: types.Message, state: FSMContext) -> None:
    try:
        dt = datetime.strptime(msg.text.strip(), "%d.%m.%Y %H:%M")
        if dt <= datetime.now():
            raise ValueError
    except ValueError:
        return await msg.reply("Неверный формат или время уже прошло.")

    mid = (await state.get_data())["edit_mid"]
    cursor.execute(
        "UPDATE mailings SET scheduled_at = ?, sent = 0 WHERE id = ?",
        (dt.isoformat(timespec="seconds"), mid),
    )
    conn.commit()

    await state.set_state(Mailing.PlannedDetail)
    await msg.reply("✅ Дата изменена.", reply_markup=planned_detail_kb(mid), parse_mode="HTML")


# --- Периодичность --------------------------------------------------------- #
@dp.callback_query(Mailing.EditMenu, F.data == "ml_edit_rec", IsAdmin())
async def ml_edit_rec_start(cb: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Mailing.EditRecurrence)
    await cb.message.edit_text("Выберите новую периодичность:", reply_markup=recurrence_kb())
    await cb.answer()


@dp.callback_query(Mailing.EditRecurrence, F.data.startswith("rec_"), IsAdmin())
async def ml_edit_rec_save(cb: types.CallbackQuery, state: FSMContext) -> None:
    rec_code = _REC_CB2CODE[cb.data]
    mid = (await state.get_data())["edit_mid"]

    cursor.execute("UPDATE mailings SET recurrence = ? WHERE id = ?", (rec_code, mid))
    conn.commit()

    await state.set_state(Mailing.PlannedDetail)
    await cb.message.edit_text("✅ Периодичность изменена.", reply_markup=planned_detail_kb(mid))
    await cb.answer()


# --------------------------------------------------------------------------- #
#                        2. ВЫБОР АУДИТОРИИ («ЦЕЛЬ»)                          #
# --------------------------------------------------------------------------- #


@dp.callback_query(Mailing.ChooseTarget, F.data.startswith("ml_"), IsAdmin())
async def ml_target_chosen(cb: types.CallbackQuery, state: FSMContext) -> None:
    """
    «ml_participants» → tiks,  «ml_staff» → категории,  
    «ml_all / ml_candidates» → сразу ввод текста.
    """
    cmd = cb.data
    await state.update_data(target=cmd, gmsid=cb.message.message_id)

    # --- участницы: выбор тиков
    if cmd == "ml_participants":
        cursor.execute(
            """
            SELECT DISTINCT tik
              FROM users
             WHERE role = 'user_participant' AND tik IS NOT NULL
          ORDER BY tik
            """
        )
        all_tiks = [str(r[0]) for r in cursor.fetchall()]
        if not all_tiks:
            return await cb.answer("Нет участниц с указанным тиком.", show_alert=True)

        await state.update_data(all_tiks=all_tiks, chosen_tiks=set())
        await state.set_state(Mailing.ChooseTik)
        await cb.message.edit_text("Выберите тики:", reply_markup=tiks_kb(all_tiks, set()))
        return await cb.answer()

    # --- сотрудники: категории
    if cmd == "ml_staff":
        await state.update_data(chosen_staff=set())
        await state.set_state(Mailing.ChooseStaff)
        await cb.message.edit_text("Выберите категории сотрудников:", reply_markup=staff_kb(set()))
        return await cb.answer()

    # --- остальные цели: сразу ввод текста
    await state.set_state(Mailing.WriteText)
    await cb.message.edit_text(
        "Введите текст рассылки:",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text="Отмена", callback_data="ml_cancel")]]
        ),
    )
    await cb.answer()


# --------------------------------------------------------------------------- #
#       2-a.  Работа с тик-чекбоксами                                         #
# --------------------------------------------------------------------------- #


@dp.callback_query(Mailing.ChooseTik, F.data.startswith("ml_tik_toggle:"), IsAdmin())
async def ml_tik_toggle(cb: types.CallbackQuery, state: FSMContext) -> None:
    tik = cb.data.split(":")[1]
    data = await state.get_data()
    chosen: Set[str] = set(data["chosen_tiks"])
    all_tiks: List[str] = data["all_tiks"]

    chosen.symmetric_difference_update({tik})
    await state.update_data(chosen_tiks=chosen)
    await cb.message.edit_reply_markup(reply_markup=tiks_kb(all_tiks, chosen))
    await cb.answer()


@dp.callback_query(Mailing.ChooseTik, F.data == "ml_tiks_done", IsAdmin())
async def ml_tiks_done(cb: types.CallbackQuery, state: FSMContext) -> None:
    chosen = (await state.get_data()).get("chosen_tiks", set())
    if not chosen:
        return await cb.answer("Нужно выбрать хотя бы один тик.", show_alert=True)

    await state.set_state(Mailing.WriteText)
    await cb.message.edit_text(
        f"Тики выбраны: {', '.join(sorted(chosen))}\n\nВведите текст рассылки:",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text="Отмена", callback_data="ml_cancel")]]
        ),
    )
    await cb.answer()


# --------------------------------------------------------------------------- #
#       2-b.  Работа с категориями сотрудников                                 #
# --------------------------------------------------------------------------- #


@dp.callback_query(Mailing.ChooseStaff, F.data.startswith("ml_staff_toggle:"), IsAdmin())
async def ml_staff_toggle(cb: types.CallbackQuery, state: FSMContext) -> None:
    code = cb.data.split(":")[1]
    data = await state.get_data()
    chosen: Set[str] = set(data.get("chosen_staff", set()))

    chosen.symmetric_difference_update({code})
    await state.update_data(chosen_staff=chosen)
    await cb.message.edit_reply_markup(reply_markup=staff_kb(chosen))
    await cb.answer()


@dp.callback_query(Mailing.ChooseStaff, F.data == "ml_staff_done", IsAdmin())
async def ml_staff_done(cb: types.CallbackQuery, state: FSMContext) -> None:
    chosen = (await state.get_data()).get("chosen_staff", set())
    if not chosen:
        return await cb.answer("Нужно выбрать хотя бы одну категорию.", show_alert=True)

    titles = {code: title for code, title in STAFF_CATEGORIES}
    names = ", ".join(titles[c] for c in chosen)

    await state.set_state(Mailing.WriteText)
    await cb.message.edit_text(
        f"Категории выбраны: {names}\n\nВведите текст рассылки:",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text="Отмена", callback_data="ml_cancel")]]
        ),
    )
    await cb.answer()


# --------------------------------------------------------------------------- #
#                        3. Ввод текста и подтверждение                       #
# --------------------------------------------------------------------------- #


@dp.message(Mailing.WriteText, IsAdmin())
async def ml_text_saved(msg: types.Message, state: FSMContext) -> None:
    await state.update_data(text=msg.md_text)
    data = await state.get_data()
    gmsid: int = data["gmsid"]

    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Отправить сейчас", callback_data="ml_send")
    kb.button(text="📅 Запланировать", callback_data="ml_set_dt")
    kb.button(text="🚫 Отмена", callback_data="ml_cancel")

    await state.set_state(Mailing.Confirm)
    await bot.edit_message_text(
        chat_id=msg.chat.id,
        message_id=gmsid,
        text="<b>Как отправляем?</b>",
        parse_mode="HTML",
        reply_markup=kb.adjust(1).as_markup(),
    )


# ---------- шаг ➊ — запрос даты ------------------------------------------- #
@dp.callback_query(Mailing.Confirm, F.data == "ml_set_dt", IsAdmin())
async def ml_set_dt(cb: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Mailing.SetSchedule)
    await cb.message.edit_text(
        "Введите дату и время в формате <b>ДД.ММ.ГГГГ ЧЧ:ММ</b>\nПример: 02.06.2025 14:30",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text="Отмена", callback_data="ml_cancel")]]
        ),
    )
    await cb.answer()


# ---------- шаг ➋ — сохраняем дату, спрашиваем период ---------------------- #
@dp.message(Mailing.SetSchedule, IsAdmin())
async def ml_save_schedule(msg: types.Message, state: FSMContext) -> None:
    try:
        dt = datetime.strptime(msg.text.strip(), "%d.%m.%Y %H:%M")
        if dt <= datetime.now():
            raise ValueError
    except ValueError:
        return await msg.reply(
            "❗️ Некорректная дата/время или момент уже в прошлом.",
            reply_markup=delete_this_msg(),
        )

    await state.update_data(scheduled_at=dt.isoformat(timespec="seconds"))
    data = await state.get_data()
    gmsid: int = data["gmsid"]

    await state.set_state(Mailing.SetRecurrence)
    await bot.edit_message_text(
        chat_id=msg.chat.id,
        message_id=gmsid,
        text="<b>Выберите периодичность</b>",
        parse_mode="HTML",
        reply_markup=recurrence_kb(),
    )


# ---------- шаг ➌ — периодичность → финальное подтверждение ---------------- #
@dp.callback_query(Mailing.SetRecurrence, F.data.startswith("rec_"), IsAdmin())
async def ml_pick_recurrence(cb: types.CallbackQuery, state: FSMContext) -> None:
    rec_code = _REC_CB2CODE[cb.data]
    await state.update_data(recurrence=rec_code)

    data = await state.get_data()
    when_human = datetime.fromisoformat(data["scheduled_at"]).strftime("%d.%m.%Y %H:%M")
    text_preview = html.quote(shorten(data["text"], 200, placeholder="…"))

    await state.set_state(Mailing.Confirm)
    await cb.message.edit_text(
        f"<b>Проверьте данные:</b>\n"
        f"• Когда: {when_human}\n"
        f"• Периодичность: {_rec_to_human(rec_code)}\n"
        f"• Текст:\n<tg-spoiler>{text_preview}</tg-spoiler>\n\n"
        "Подтвердить?",
        parse_mode="HTML",
        reply_markup=confirm_kb(),
    )
    await cb.answer()


# ---------- финальное «Запланировать» -------------------------------------- #
@dp.callback_query(Mailing.Confirm, F.data == "ml_plan_confirm", IsAdmin())
async def ml_plan_confirm(cb: types.CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    filters = {
        "target": data["target"],
        "chosen_tiks": sorted(list(data.get("chosen_tiks", []))),
        "chosen_staff": sorted(list(data.get("chosen_staff", []))),
    }

    cursor.execute(
        """
        INSERT INTO mailings (title, message, scheduled_at, sent, filters, recurrence)
        VALUES ('scheduled', ?, ?, 0, ?, ?)
        """,
        (data["text"], data["scheduled_at"], json.dumps(filters), data["recurrence"]),
    )
    conn.commit()

    await state.clear()
    await cb.message.edit_text(
        "✅ Рассылка успешно запланирована.", reply_markup=get_superadmin_panel_kb()
    )
    await cb.answer()


# --------------------------------------------------------------------------- #
#                          4. ОТПРАВКА «СЕЙЧАС»                               #
# --------------------------------------------------------------------------- #


@dp.callback_query(Mailing.Confirm, F.data == "ml_send", IsAdmin())
async def ml_do_send(cb: types.CallbackQuery, state: FSMContext) -> None:
    await cb.answer("Отправка рассылки, это может занять некоторое время…", show_alert=True)
    data = await state.get_data()
    users = _collect_recipients(data)
    if not users:
        await cb.answer("Пользователи не найдены.", show_alert=True)
        await state.clear()
        return

    sent = failed = 0
    for uid in users:
        try:
            await bot.send_message(uid, data["text"], parse_mode="HTML")
            sent += 1
        except TelegramAPIError:
            failed += 1

    cursor.execute(
        "INSERT INTO mailings (title, message, scheduled_at, sent) VALUES ('manual', ?, ?, 1)",
        (data["text"], datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()

    await state.clear()
    await cb.message.edit_text(
        f"Рассылка отправлена.\nДоставлено: {sent}\nОшибок: {failed}",
        reply_markup=targets_kb(),
    )
    await cb.answer()


# --------------------------------------------------------------------------- #
#                          5. КНОПКИ «НАЗАД»                                  #
# --------------------------------------------------------------------------- #


@dp.callback_query(
    Mailing.ViewPlanned,
    F.data == "ml_back_targets",
    IsAdmin(),
)
@dp.callback_query(
    Mailing.ChooseTik,
    F.data == "ml_back_targets",
    IsAdmin(),
)
@dp.callback_query(
    Mailing.ChooseStaff,
    F.data == "ml_back_targets",
    IsAdmin(),
)
async def ml_back_targets(cb: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Mailing.ChooseTarget)
    await cb.message.edit_text(
        "Кому вы хотите отправить рассылку?", reply_markup=targets_kb()
    )
    await cb.answer()
