"""
Registration flow for “Practice Supervisor” (РП).
"""

from __future__ import annotations

from typing import Optional

from aiogram import F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import CallbackQuery, Message

from admins.filters.is_admin import IsAdmin
from admins.practice_supervisor.registration.keyboards import (
    get_departments_kb,
    get_modules_kb_for_rp,
    get_ps_register_kb,
    get_ps_request_approval_kb,  # клавиатура с «Одобрить» / «Отклонить»
)

from admins.practice_supervisor.registration.states import (
    PSModuleAfterApprove,
    PSRegister,
)
from config import bot, dp, request_bot_user_chat_id
from db.database import (
    create_ps_request,
    delete_ps_request,
    find_ps_by_full_name,
    get_ps_request_by_id,
    get_username,
    has_pending_ps_request,
    insert_practice_supervisor,
    set_user_role,
    update_ps_request_status,
    update_ps_user_id,
)

# --------------------------------------------------------------------------- #
#                        1.  ЗАПУСК РЕГИСТРАЦИИ                               #
# --------------------------------------------------------------------------- #


@dp.callback_query(F.data == "ps_register")
async def ps_register_start(cb: CallbackQuery, state: FSMContext) -> None:
    """Кнопка «Зарегистрироваться» — спрашиваем ФИО."""
    await cb.answer()

    uid = cb.from_user.id
    if has_pending_ps_request(uid):
        await cb.message.edit_text(
            "❗ У вас уже есть незавершённая заявка на регистрацию руководителя "
            "практики. Ожидайте решения администраторов."
        )
        return

    await state.set_state(PSRegister.WaitingFullName)
    await cb.message.edit_text("✍️ Пожалуйста, введите ваше ФИО для регистрации:")


# --------------------------------------------------------------------------- #
#                       2.  ОБРАБОТКА ВВЕДЕННОГО ФИО                          #
# --------------------------------------------------------------------------- #


@dp.message(PSRegister.WaitingFullName)
async def ps_register_fullname(msg: Message, state: FSMContext) -> None:
    """
    • Точный матч → запрос «существующий РП».  
    • Нет матча   → сохраняем ФИО и просим подразделение.
    """
    full_name = msg.text.strip()
    uid = msg.from_user.id

    if has_pending_ps_request(uid):
        await msg.answer(
            "❗ У вас уже есть незавершённая заявка. Дождитесь её обработки."
        )
        return await state.clear()

    ps = find_ps_by_full_name(full_name)
    if ps:
        # ─── существующий РП ───
        if ps["user_id"]:
            await msg.answer(
                "❗ Эта запись уже привязана к другому Telegram-аккаунту."
            )
            return await state.clear()

        req_id = create_ps_request(
            user_id=uid,
            full_name=full_name,
            department=ps["department"],
            module=ps["module"],
            is_existing=True,
            ps_id=ps["id"],
        )
        await _notify_admins_about_request(
            full_name,
            ps["department"],
            ps["module"],
            req_id,
            uid,
            msg.from_user.username,
            is_existing=True,
        )
        await msg.answer("✅ Запрос отправлен администраторам.")
        return await state.clear()

    # ─── новый РП ───
    await state.update_data(fio=full_name)
    await state.set_state(PSRegister.WaitingDepartment)
    await msg.answer(
        "⚠️ ФИО не найдено. Выберите ваше подразделение:",
        reply_markup=get_departments_kb(),
    )


# --------------------------------------------------------------------------- #
#                         3.  ВЫБОР ПОДРАЗДЕЛЕНИЯ                             #
# --------------------------------------------------------------------------- #


@dp.callback_query(PSRegister.WaitingDepartment, F.data.startswith("ps_dept:"))
async def ps_register_department(cb: CallbackQuery, state: FSMContext) -> None:
    """После выбора отдела создаём pending-запрос (модуль узнаем позднее)."""
    await cb.answer()

    # департамент, выбранный пользователем
    _, encoded = cb.data.split(":", maxsplit=1)
    department = encoded.replace("_", ":")

    # сохраняем департамент и переходим к модулю
    await state.update_data(department=department)
    await state.set_state(PSRegister.WaitingModule)
    await cb.message.edit_text(
        "✍️ Пожалуйста, укажите <b>модуль</b> текстом:",
        parse_mode="HTML"
    )

@dp.message(PSRegister.WaitingModule)
async def ps_register_module(msg: Message, state: FSMContext) -> None:
    """Получаем модуль, создаём pending-заявку, шлём её в админ-чат."""
    module = msg.text.strip()
    uid = msg.from_user.id

    if has_pending_ps_request(uid):
        await msg.answer(
            "❗ У вас уже есть незавершённая заявка на регистрацию руководителя "
            "практики. Ожидайте решения администраторов."
        )
        return

    data = await state.get_data()
    full_name: str = data["fio"]
    department: str = data["department"]

    req_id = create_ps_request(
        user_id=uid,
        full_name=full_name,
        department=department,
        module=module,
        is_existing=False,
        ps_id=None,
    )

    await _notify_admins_about_request(
        full_name,
        department,
        module,
        req_id,
        uid,
        msg.from_user.username,
        is_existing=False,
    )

    await msg.answer("✅ Заявка на регистрацию отправлена администраторам.")
    await state.clear()


# --------------------------------------------------------------------------- #
#                    4.  ОДОБРЕНИЕ / ОТКЛОНЕНИЕ ЗАЯВОК                        #
# --------------------------------------------------------------------------- #


@dp.callback_query(F.data.startswith("ps_approve:"), IsAdmin())
async def ps_request_approve(cb: CallbackQuery, state: FSMContext) -> None:
    """Кнопка «Разрешить доступ» в админ-чате."""
    await _process_admin_decision(cb, approved=True, state=state)


@dp.callback_query(F.data.startswith("ps_reject:"), IsAdmin())
async def ps_request_reject(cb: CallbackQuery) -> None:
    """Кнопка «Отклонить» в админ-чате."""
    await _process_admin_decision(cb, approved=False, state=None)


# --------------------------------------------------------------------------- #
#            5.  РП ВЫБИРАЕТ МОДУЛЬ ПОСЛЕ ОДОБРЕНИЯ НОВОЙ ЗАЯВКИ              #
# --------------------------------------------------------------------------- #


@dp.callback_query(
    PSModuleAfterApprove.WaitingModule,
    F.data.startswith("ps_rp_module:"),
    IsAdmin(),
)
async def ps_module_after_approve(cb: CallbackQuery, state: FSMContext) -> None:
    """
    Callback «ps_rp_module:{request_id}:{module_encoded}» от РП
    после одобрения новой заявки.
    """
    await cb.answer()

    try:
        _, req_id_str, module_encoded = cb.data.split(":", maxsplit=2)
        req_id = int(req_id_str)
        module = module_encoded.replace("_", ":")
    except ValueError:
        return await cb.answer("Некорректные данные.", show_alert=True)

    req = get_ps_request_by_id(req_id)
    if not req or req["status"] != "approved":
        await cb.answer("Заявка не найдена или уже обработана.", show_alert=True)
        return await state.clear()

    uid = req["user_id"]

    insert_practice_supervisor(
        full_name=req["full_name"],
        department=req["department"],
        module=module,
        user_id=uid,
    )
    set_user_role(uid, "admin_practice_supervisor")
    update_ps_request_status(req_id, "completed")
    delete_ps_request(req_id)

    await bot.send_message(
        uid,
        "✅ Модуль сохранён, регистрация завершена!\nВведите /admin для доступа.",
    )
    await state.clear()


# --------------------------------------------------------------------------- #
#                               ВСПОМОГАТЕЛЬНЫЕ                               #
# --------------------------------------------------------------------------- #


async def _notify_admins_about_request(
    full_name: str,
    department: str,
    module: Optional[str],
    request_id: int,
    uid: int,
    username: Optional[str],
    is_existing: bool,
) -> None:
    """
    Отправляет карточку заявки в сервис-чат администраторов.

    • «существующий» — запись уже есть в БД, только привязываем user_id;  
    • «новый» — полностью новая регистрация РП.
    """
    status = "существующий" if is_existing else "новый"

    text = (
        f"📩 <b>Новый запрос на регистрацию РП ({status})</b>\n\n"
        f"<b>ФИО:</b> {full_name}\n"
        f"<b>Подразделение:</b> {department}\n"
        f"<b>Модуль:</b> {module or '—'}\n"
        f"<b>UserID:</b> <code>{uid}</code>\n"
        f"<b>Username:</b> @{username or '—'}\n\n"
        "Нажмите «<b>Одобрить</b>» или «<b>Отклонить</b>»"
    )

    await bot.send_message(
        request_bot_user_chat_id,
        text,
        parse_mode="HTML",
        reply_markup=get_ps_request_approval_kb(request_id),
    )



async def _process_admin_decision(
    cb: CallbackQuery, *, approved: bool, state: Optional[FSMContext]
) -> None:
    """
    Общая логика для «Одобрить» и «Отклонить».

    • Берём id заявки из callback-data.  
    • Получаем строку заявки через get_ps_request_by_id.  
    • Превращаем sqlite3.Row → dict, чтобы downstream-функции могли
      использовать .get().  
    • Делегируем в _handle_approval / _handle_reject.
    """
    try:
        req_id = int(cb.data.split(":", maxsplit=1)[1])
    except ValueError:
        return await cb.answer("Некорректный ID.", show_alert=True)

    req_row = get_ps_request_by_id(req_id)
    if not req_row or req_row["status"] != "pending":
        return await cb.answer("Запрос не найден или уже обработан.", show_alert=True)

    req: dict = dict(req_row)  # sqlite3.Row → dict ✅

    if approved:
        await _handle_approval(cb, req, state)
    else:
        await _handle_reject(cb, req)


# ─────────────────────────  ОДОБРЕНИЕ  ─────────────────────────
async def _handle_approval(
    cb: CallbackQuery, req: dict, state: Optional[FSMContext]
) -> None:
    """
    Одобрение заявки руководителя практики.

    1️⃣ Существующий РП – привязываем user_id к записи и выдаём роль.  
    2️⃣ Новый РП:
        • если модуль УЖЕ указан (новая форма регистрации) – сразу заводим
          запись и выдаём роль;  
        • если модуля нет (старые заявки) – запрашиваем модуль через
          клавиатуру и переводим РП в FSM-ожидание.
    """
    uid = req["user_id"]
    username = get_username(uid)

    # -------- 1. Уже существующий РП --------
    if req["is_existing"]:
        update_ps_user_id(req["ps_id"], uid)
        set_user_role(uid, "admin_practice_supervisor")
        update_ps_request_status(req["id"], "approved")
        delete_ps_request(req["id"])

        await bot.send_message(
            uid,
            "🎉 Заявка одобрена! Ваш модуль уже зафиксирован.\nВведите /admin.",
        )
        await _edit_admin_msg(
            cb,
            "✅ <b>Заявка одобрена</b> (существующий РП)",
            req,
            username,
        )
        return await cb.answer("Доступ предоставлен.")

    # -------- 2. Новый РП, модуль уже есть --------
    if req.get("module"):
        insert_practice_supervisor(
            full_name=req["full_name"],
            department=req["department"],
            module=req["module"],
            user_id=uid,
        )
        set_user_role(uid, "admin_practice_supervisor")
        update_ps_request_status(req["id"], "approved")
        delete_ps_request(req["id"])

        await bot.send_message(
            uid,
            "🎉 Ваша заявка одобрена!\nВведите /practice для доступа к панели.",
        )
        await _edit_admin_msg(cb, "✅ <b>Заявка одобрена</b>", req, username)
        await cb.answer("Запрос одобрен.")
        return

    # -------- 3. Новый РП, модуль ещё не выбран (fallback) --------
    update_ps_request_status(req["id"], "approved")

    kb = get_modules_kb_for_rp(department=req["department"], req_id=req["id"])
    await bot.send_message(
        uid,
        "🎉 Заявка одобрена!\n✍️ Выберите модуль:",
        reply_markup=kb,
    )
    await _edit_admin_msg(
        cb,
        "✅ <b>Заявка одобрена</b> (ожидание модуля)",
        req,
        username,
    )

    # переводим пользователя в FSM-ожидание модуля
    rp_state = FSMContext(
        storage=dp.storage,
        key=StorageKey(chat_id=uid, user_id=uid, bot_id=bot.id),
    )
    await rp_state.set_state(PSModuleAfterApprove.WaitingModule)
    await rp_state.update_data(request_id=req["id"])

    await cb.answer("Запрос одобрен. Ожидаем модуль от РП.")


# ─────────────────────────  ОТКЛОНЕНИЕ  ─────────────────────────
async def _handle_reject(cb: CallbackQuery, req: dict) -> None:
    """Отклонение заявки руководителя практики."""
    uid = req["user_id"]
    update_ps_request_status(req["id"], "rejected")
    delete_ps_request(req["id"])

    await bot.send_message(uid, "🚫 Ваша заявка отклонена.")
    await _edit_admin_msg(cb, "❗ <b>Заявка отклонена</b>", req, get_username(uid))
    await cb.answer("Заявка отклонена.")



async def _edit_admin_msg(
    cb: CallbackQuery, header: str, req: dict, username: Optional[str]
) -> None:
    """Обновляем карточку заявки в чате админов."""
    text = (
        f"{header}\n\n"
        f"ФИО: <i>{req['full_name']}</i>\n"
        f"Подразделение: <i>{req['department']}</i>\n"
        f"Модуль: <i>{req.get('module') or '—'}</i>\n"
        f"UserID: <code>{req['user_id']}</code>\n"
        f"Username: @{username or '—'}"
    )
    await cb.message.edit_reply_markup()
    await cb.message.edit_text(text, parse_mode="HTML")
