"""
Super-admin FAQ editor
======================

Позволяет:
* выбирать роль и просматривать её FAQ с пагинацией;
* создавать, редактировать и удалять пункты FAQ;
* выгружать / загружать Excel для «Кандидатки».

Главные FSM-состояния описаны в  *states.py*.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Final, Iterable, List, Optional, Tuple

from aiogram import F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from admins.filters.is_admin import IsAdmin
from admins.keyboards import delete_this_msg
from admins.superadmin.faq.keyboards import (
    confirm_edit_kb,
    confirm_kb,
    faq_item_kb,
    faq_list_kb,
    role_menu_kb,
    roles_kb,
)
from admins.superadmin.faq.states import FaqStates
from config import ROLES, bot, dp
from db.database import conn, cursor
from user.registration.utils import info as info_mod  # excel-FAQ «Кандидатка»

XL_PATH: Final = (
    Path(__file__).resolve().parents[3]
    / "user"
    / "registration"
    / "utils"
    / "excel"
    / "info.xlsx"
)


# --------------------------------------------------------------------------- #
#                          1. ВЫБОР РОЛИ                                      #
# --------------------------------------------------------------------------- #
@dp.callback_query(F.data == "sa_faq", IsAdmin())
async def faq_entry(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Корневая точка меню «📚 FAQ»."""
    await state.clear()
    await state.update_data(page=0)
    await state.set_state(FaqStates.SelectRole)

    await cb.message.edit_text(
        "Выберите роль, FAQ которой нужно отредактировать:",
        reply_markup=roles_kb(0),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("faq_roles_page:"), IsAdmin())
async def faq_roles_page(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Пагинация списка ролей."""
    page: int = int(cb.data.split(":")[1])
    await state.update_data(page=page)
    await cb.message.edit_reply_markup(reply_markup=roles_kb(page))
    await cb.answer()


@dp.callback_query(F.data.startswith("faq_role:"), IsAdmin())
async def faq_role_selected(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Переходим к меню конкретной роли."""
    role_code: str = cb.data.split(":")[1]
    await state.update_data(role=role_code)
    await state.set_state(FaqStates.RoleMenu)

    await cb.message.edit_text(
        f"Управление FAQ – <b>{ROLES[role_code]}</b>",
        parse_mode="HTML",
        reply_markup=role_menu_kb(role_code),
    )
    await cb.answer()


@dp.callback_query(F.data == "faq_roles_root", IsAdmin())
async def faq_roles_root(cb: types.CallbackQuery, state: FSMContext) -> None:
    """«Назад» из меню роли в список ролей (с сохранением страницы)."""
    page = (await state.get_data()).get("page", 0)
    await state.set_state(FaqStates.SelectRole)

    await cb.message.edit_text(
        "Выберите роль, FAQ которой нужно отредактировать:",
        reply_markup=roles_kb(page),
    )
    await cb.answer()


# --------------------------------------------------------------------------- #
#                          2. СПИСОК FAQ + ПУНКТ                              #
# --------------------------------------------------------------------------- #
@dp.callback_query(F.data.startswith("faq_list:"), IsAdmin())
async def faq_list(cb: types.CallbackQuery) -> None:
    """Отображаем список вопросов с пагинацией."""
    _, role_code, page_str = cb.data.split(":")
    page = int(page_str)

    cursor.execute(
        "SELECT id, question FROM faq WHERE for_role = ? ORDER BY id", (role_code,)
    )
    questions: List[Tuple[int, str]] = cursor.fetchall()

    await cb.message.edit_text(
        f"FAQ для роли <b>{ROLES[role_code]}</b> (всего {len(questions)}):",
        parse_mode="HTML",
        reply_markup=faq_list_kb(role_code, page, questions),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("faq_q:"), IsAdmin())
async def faq_open_item(cb: types.CallbackQuery) -> None:
    """Открываем один пункт FAQ (вопрос + ответ)."""
    _, role_code, qid_str = cb.data.split(":")
    qid = int(qid_str)

    cursor.execute("SELECT question, answer FROM faq WHERE id = ?", (qid,))
    row = cursor.fetchone()
    if not row:
        return await cb.answer("Пункт не найден", show_alert=True)

    question, answer = row
    text = f"<b>{question}</b>\n\n{answer}"

    await cb.message.edit_text(
        text, parse_mode="HTML", reply_markup=faq_item_kb(role_code, qid)
    )
    await cb.answer()


# --------------------------------------------------------------------------- #
#                       3.  РЕДАКТИРОВАНИЕ  ПУНКТА                            #
# --------------------------------------------------------------------------- #
@dp.callback_query(F.data.startswith("faq_edit:"), IsAdmin())
async def faq_edit_start(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Старт редактирования вопроса → ждём новый текст вопроса."""
    _, role_code, qid_str = cb.data.split(":")
    qid = int(qid_str)

    await state.update_data(role=role_code, qid=qid, msg_q_id=cb.message.message_id)
    await state.set_state(FaqStates.EditQ)

    await cb.message.edit_text(
        "Введите <b>новый вопрос</b>\n(или отправьте «-», чтобы оставить прежний):",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [types.InlineKeyboardButton(text="Назад", callback_data=f"faq_q:{role_code}:{qid}")]
            ]
        ),
    )
    await cb.answer()


@dp.message(FaqStates.EditQ, IsAdmin())
async def faq_edit_q(msg: types.Message, state: FSMContext) -> None:
    """Получаем новый вопрос → запрашиваем новый ответ."""
    await state.update_data(new_q=None if msg.text == "-" else msg.text.strip())
    await state.set_state(FaqStates.EditA)

    data = await state.get_data()
    old_q = cursor.execute(
        "SELECT question FROM faq WHERE id = ?", (data["qid"],)
    ).fetchone()[0]

    await msg.delete()

    await bot.edit_message_text(
        chat_id=msg.chat.id,
        message_id=data["msg_q_id"],
        text=(
            f"Вопрос: {data['new_q'] or old_q}\n\n"
            "Введите <b>новый ответ</b>\n(или «-», чтобы не менять):"
        ),
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="Назад", callback_data=f"faq_q:{data['role']}:{data['qid']}"
                    )
                ]
            ]
        ),
    )


@dp.message(FaqStates.EditA, IsAdmin())
async def faq_edit_a(msg: types.Message, state: FSMContext) -> None:
    """Получили новый ответ → показываем предварительный просмотр."""
    await state.update_data(new_a=None if msg.text == "-" else msg.text.strip())
    data = await state.get_data()

    old_q, old_a = cursor.execute(
        "SELECT question, answer FROM faq WHERE id = ?", (data["qid"],)
    ).fetchone()

    new_q, new_a = data["new_q"] or old_q, data["new_a"] or old_a
    await msg.delete()

    await state.set_state(FaqStates.ConfirmEdit)
    await bot.edit_message_text(
        chat_id=msg.chat.id,
        message_id=data["msg_q_id"],
        text=f"Проверьте:\n<b>Вопрос:</b> {new_q}\n<b>Ответ:</b> {new_a}",
        parse_mode="HTML",
        reply_markup=confirm_edit_kb(data["role"], data["qid"]),
    )


@dp.callback_query(F.data.startswith("faq_update:"), IsAdmin())
async def faq_update(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Сохраняем изменения после подтверждения."""
    data = await state.get_data()
    role_code, qid_str = cb.data.split(":")[1:]
    qid = int(qid_str)

    old_q, old_a = cursor.execute(
        "SELECT question, answer FROM faq WHERE id = ?", (qid,)
    ).fetchone()

    new_q = data.get("new_q") or old_q
    new_a = data.get("new_a") or old_a

    cursor.execute(
        "UPDATE faq SET question = ?, answer = ? WHERE id = ?", (new_q, new_a, qid)
    )
    conn.commit()

    await state.set_state(FaqStates.RoleMenu)
    await cb.message.edit_text("✅ Изменения сохранены.", reply_markup=role_menu_kb(role_code))
    await cb.answer("Обновлено!")


@dp.callback_query(F.data.startswith("faq_edit_cancel:"), IsAdmin())
async def faq_edit_cancel(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Отмена редактирования → возвращаемся к пункту FAQ."""
    _, role_code, qid = cb.data.split(":")
    await state.clear()
    await faq_open_item(cb)  # повторно показываем пункт
    await cb.answer()


@dp.callback_query(F.data.startswith("faq_del:"), IsAdmin())
async def faq_delete(cb: types.CallbackQuery) -> None:
    """Удаление пункта FAQ без подтверждения (soft-confirm в Telegram)."""
    _, role_code, qid_str = cb.data.split(":")
    qid = int(qid_str)

    cursor.execute("DELETE FROM faq WHERE id = ?", (qid,))
    conn.commit()

    await cb.message.edit_text("🗑 Пункт удалён.", reply_markup=role_menu_kb(role_code))
    await cb.answer("Удалено!")


# --------------------------------------------------------------------------- #
#                 4. EXCEL-ИМПОРТ / ЭКСПОРТ  «Кандидатка»                     #
# --------------------------------------------------------------------------- #
@dp.callback_query(F.data == "faq_candidate", IsAdmin())
async def faq_cand_root(cb: types.CallbackQuery) -> None:
    """Меню FAQ «Кандидатка» (специальный код `user_unauthorized`)."""
    await cb.message.edit_text(
        "Управление FAQ – <b>Кандидатка</b>",
        parse_mode="HTML",
        reply_markup=role_menu_kb("user_unauthorized"),
    )
    await cb.answer()


@dp.callback_query(F.data == "faq_export_cand", IsAdmin())
async def faq_export_cand(cb: types.CallbackQuery) -> None:
    """Отправляем admin-у Excel-шаблон для «Кандидатки»."""
    if not XL_PATH.exists():
        return await cb.answer("Файл info.xlsx не найден.", show_alert=True)

    await bot.send_document(
        cb.from_user.id, types.FSInputFile(XL_PATH, filename="faq_candidate.xlsx")
    )
    await cb.answer()


@dp.callback_query(F.data == "faq_import_cand", IsAdmin())
async def faq_import_cand_start(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Ждём загрузки Excel со стороны суперадмина."""
    await cb.message.edit_text(
        "Отправьте Excel-файл, он должен соответствовать структуре экспортируемого файла.",
        reply_markup=role_menu_kb("user_unauthorized"),
    )
    await state.set_state(FaqStates.UploadExcel)
    await cb.answer()


@dp.message(FaqStates.UploadExcel, IsAdmin(), F.document)
async def faq_handle_excel(msg: types.Message, state: FSMContext) -> None:
    """Принимаем Excel → валидируем → заменяем `info.xlsx`."""
    doc = msg.document
    if not doc.file_name.lower().endswith(".xlsx"):
        return await msg.reply("Нужен файл *.xlsx*")

    tmp_path = Path("tmp") / f"cand_faq_{doc.file_id}.xlsx"
    tmp_path.parent.mkdir(exist_ok=True)

    await bot.download(doc, destination=tmp_path)

    # ─── валидация: ≥1 строка и ≥12 колонок (6 Q, 6 A) ───
    import pandas as pd

    try:
        df = pd.read_excel(tmp_path, engine="openpyxl", header=None)
    except Exception as exc:  # pylint: disable=broad-except
        tmp_path.unlink(missing_ok=True)
        return await msg.reply(f"Ошибка чтения файла: {exc}")

    if df.shape[0] == 0 or df.shape[1] < 12:
        tmp_path.unlink(missing_ok=True)
        return await msg.reply("Структура файла не соответствует шаблону info.xlsx.")

    XL_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.replace(XL_PATH)

    # «горячо» перезагружаем модуль, чтобы новые данные подхватились
    importlib.reload(info_mod)

    await state.clear()
    await msg.reply(
        f"✅ Импорт завершён. Загружено строк: {df.shape[0]}",
        reply_markup=delete_this_msg(),
    )


# --------------------------------------------------------------------------- #
#                       5. СОЗДАНИЕ НОВОГО ПУНКТА                             #
# --------------------------------------------------------------------------- #
@dp.callback_query(F.data.startswith("faq_create:"), IsAdmin())
async def faq_create_start(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Шаг 1 — запрашиваем «кнопку» (question)."""
    role_code = cb.data.split(":")[1]
    await state.update_data(role=role_code, msg_new_id=cb.message.message_id)
    await state.set_state(FaqStates.CreateQ)

    kb_back = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="Назад", callback_data=f"faq_role_back:{role_code}"
                )
            ]
        ]
    )
    await cb.message.edit_text(
        f"Введите <b>название кнопки</b> FAQ для роли {ROLES[role_code]}:",
        parse_mode="HTML",
        reply_markup=kb_back,
    )
    await cb.answer()


@dp.message(FaqStates.CreateQ, IsAdmin())
async def faq_create_title(msg: types.Message, state: FSMContext) -> None:
    """Шаг 2 — получаем вопрос, переходим к ответу."""
    await state.update_data(title=msg.text.strip())
    role_code = (await state.get_data())["role"]

    await state.set_state(FaqStates.CreateA)
    await bot.edit_message_text(
        chat_id=msg.chat.id,
        message_id=(await state.get_data())["msg_new_id"],
        text="Введите <b>текст</b> FAQ:",
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="Назад", callback_data=f"faq_role_back:{role_code}"
                    )
                ]
            ]
        ),
    )
    await msg.delete()


@dp.message(FaqStates.CreateA, IsAdmin())
async def faq_create_answer(msg: types.Message, state: FSMContext) -> None:
    """Предпросмотр и подтверждение нового пункта."""
    await state.update_data(answer=msg.text.strip())
    data = await state.get_data()

    await state.set_state(FaqStates.ConfirmCreate)
    await bot.edit_message_text(
        chat_id=msg.chat.id,
        message_id=data["msg_new_id"],
        text=(
            "Проверьте данные:\n"
            f"<b>Название:</b> {data['title']}\n"
            f"<b>Текст:</b> {data['answer']}"
        ),
        parse_mode="HTML",
        reply_markup=confirm_kb(data["role"]),
    )
    await msg.delete()


@dp.callback_query(F.data.startswith("faq_save:"), IsAdmin())
async def faq_save(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Сохраняем новый пункт FAQ."""
    data = await state.get_data()
    role_code = data["role"]

    cursor.execute(
        "INSERT INTO faq(question, answer, for_role) VALUES(?, ?, ?)",
        (data["title"], data["answer"], role_code),
    )
    conn.commit()

    await state.set_state(FaqStates.RoleMenu)
    await cb.message.edit_text("✅ Пункт добавлен!", reply_markup=role_menu_kb(role_code))
    await cb.answer("FAQ добавлен!")


@dp.callback_query(F.data.startswith("faq_role_back:"), IsAdmin())
async def faq_role_back(cb: types.CallbackQuery, state: FSMContext) -> None:
    """«Назад» из процесса создания к меню роли."""
    role_code = cb.data.split(":")[1]
    await state.set_state(FaqStates.RoleMenu)
    await cb.message.edit_text(
        f"Управление FAQ – <b>{ROLES[role_code]}</b>",
        parse_mode="HTML",
        reply_markup=role_menu_kb(role_code),
    )
    await cb.answer()
