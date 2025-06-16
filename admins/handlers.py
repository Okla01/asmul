"""
Хэндлеры верхнего уровня для админ-панели.

Содержит:
* вход в панель в зависимости от роли (`/admin`);
* выбор и смена собственных ролей (`set_my_role`, callback `setrole:*`);
* служебные команды – экспорт и импорт Excel-файлов, отправка chat_id,
  перезапуск бота и т. д.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path
from typing import Final, Optional

from aiogram import F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile

from admins.filters.allowed_ids import AllowedIDs
from admins.filters.is_admin import IsAdmin
from admins.keyboards import (
    get_admin_panel_kb,
    get_import_files_kb,
    get_practice_supervisor_panel_kb,
    get_superadmin_panel_kb,
    _role_kb,
    delete_this_msg,
)
from admins.states import ImportFSM
from config import ROLES, bot, dp, IMPORT_FILES
from db.database import (
    export_candidates_zip_async,
    get_user_role,
    set_user_role,
)
from user.registration.utils.locale_to_excel import import_excel_to_db

# --------------------------------------------------------------------------- #
#                               ВСПОМОГАТЕЛЬНОЕ                               #
# --------------------------------------------------------------------------- #


def _role_suffix(role_code: str) -> str:
    """
    Утилита: берём то, что после первого «_» (или само значение, если подчёркивания нет).

    Пример:
        >>> _role_suffix("practice_supervisor") -> "practice_supervisor"
        >>> _role_suffix("user_unauthorized")   -> "unauthorized"
    """
    if "_" not in role_code:
        return role_code
    # split(maxsplit=1) даёт ["user", "unauthorized"] – берём хвост
    return role_code.split("_", maxsplit=1)[1]


# --------------------------------------------------------------------------- #
#                              ОСНОВНОЕ МЕНЮ /admin                           #
# --------------------------------------------------------------------------- #


@dp.message(Command("admin"), IsAdmin())
async def admin_entry(message: types.Message, state: FSMContext) -> None:
    """
    Хэндлер для «админских» ролей – показывает нужную панель.

    * practice_supervisor  → панель РП
    * admin                → панель администратора
    * supervisor           → панель суперадмина
    """
    await state.clear()

    suffix: str = _role_suffix(get_user_role(message.from_user.id) or "")
    if suffix == "practice_supervisor":
        await message.answer("Панель руководителя практики",
                             reply_markup=get_practice_supervisor_panel_kb())
    elif suffix == "admin":
        await message.answer("Панель админа", reply_markup=get_admin_panel_kb())
    elif suffix == "supervisor":
        await message.answer("Панель суперадмина",
                             reply_markup=get_superadmin_panel_kb())
    # если роль не админская – просто молчим, чтобы второму хэндлеру не мешать


@dp.message(Command("admin"))
async def admin_entry_show_ps_registration(
    message: types.Message, state: FSMContext
) -> None:
    """
    Для обычного пользователя: предлагает зарегистрироваться как РП.
    Срабатывает **только если предыдущий хэндлер не вернул ответ**.
    """
    await state.clear()

    suffix: str = _role_suffix(get_user_role(message.from_user.id)
                               or "user_unauthorized")
    if suffix not in ("practice_supervisor", "admin", "supervisor"):
        from admins.practice_supervisor.registration.keyboards import (
            get_ps_register_kb,
        )

        await message.answer(
            "Чтобы получить доступ к панели руководителя практики, "
            "зарегистрируйтесь:",
            reply_markup=get_ps_register_kb(),
        )


# ---------------------------- ПРОЧИЕ КОЛЛБЭКИ ----------------------------- #


@dp.callback_query(F.data == "sa_menu")
async def sa_menu_h(cb: types.CallbackQuery) -> None:
    """Переход к корневому меню суперадмина."""
    await cb.message.edit_text(
        "Панель суперадмина", reply_markup=get_superadmin_panel_kb()
    )


@dp.message(Command("set_my_role"))
async def send_role_chooser(msg: types.Message) -> None:
    """Показывает инлайн-клавиатуру со всеми доступными ролями."""
    role = get_user_role(msg.from_user.id) or "—"
    text = (
        f"Ваша текущая роль: <b>{ROLES.get(role, role)}</b>\n\n"
        "Выберите, на какую роль хотите переключиться:"
    )
    await msg.answer(text, reply_markup=_role_kb(role), parse_mode="HTML")


@dp.callback_query(F.data.startswith("setrole:"))
async def change_role(cb: types.CallbackQuery) -> None:
    """Сохраняет новую роль пользователя."""
    new_role: str = cb.data.split(":", 1)[1]
    user_id: int = cb.from_user.id

    if get_user_role(user_id) == new_role:
        await cb.answer("Эта роль уже выбрана ✅", show_alert=True)
        return

    set_user_role(user_id, new_role)

    await cb.message.edit_text(
        f"Ваша роль обновлена на: <b>{ROLES[new_role]}</b>\n\n"
        "Чтобы изменить ещё раз — нажмите кнопку ниже:",
        reply_markup=_role_kb(new_role),
        parse_mode="HTML",
    )
    await cb.answer("Роль успешно изменена!")


# --------------------------------------------------------------------------- #
#                        ЭКСПОРТ и  ИМПОРТ  Excel-ФАЙЛОВ                      #
# --------------------------------------------------------------------------- #


class ReloadCand(StatesGroup):
    """FSM: одно состояние, в котором ждём Excel с переводами."""
    waiting_for_file = State()


@dp.message(Command("get_archive"), AllowedIDs())
async def cmd_get_archive(msg: types.Message) -> None:
    """Отправляет zip-архив с кандидатами (для суперадмина/рута)."""
    zip_path: Path = await export_candidates_zip_async(bot)
    await bot.send_document(msg.chat.id, FSInputFile(zip_path))


@dp.message(Command("reload_cand"), AllowedIDs())
async def cmd_reload_translations(msg: types.Message, state: FSMContext) -> None:
    """Запускает процесс загрузки нового translations.xlsx."""
    await msg.answer(
        "Отправьте Excel-файл (.xlsx) с переводами 📄", reply_markup=delete_this_msg()
    )
    await state.set_state(ReloadCand.waiting_for_file)


@dp.message(
    ReloadCand.waiting_for_file,
    IsAdmin(),
    lambda m: (
        m.document
        and m.document.file_name
        and m.document.file_name.lower().endswith(".xlsx")
    ),
)
async def process_excel(msg: types.Message, state: FSMContext) -> None:
    """
    Получили файл с переводами → сохраняем и вызываем import_excel_to_db().
    Особенность Windows – возможна задержка появления файла на диске.
    """
    utils_dir: Path = Path("user", "registration", "utils")
    utils_dir.mkdir(parents=True, exist_ok=True)
    save_path: Path = utils_dir / "translations.xlsx"

    try:
        await bot.download(msg.document.file_id, destination=save_path)
    except Exception as exc:
        await msg.answer(f"⚠️ Скачивание не удалось: {exc}")
        await state.clear()
        return

    # Дожидаемся появления файла (актуально для Windows)
    for _ in range(10):  # ≈ 1 секунда макс.
        if save_path.exists():
            break
        await asyncio.sleep(0.1)
    else:
        await msg.answer("⚠️ Файл так и не появился на диске.")
        await state.clear()
        return

    try:
        import_excel_to_db()
    except Exception as exc:
        await msg.answer(
            f"⚠️ Файл сохранён, но ошибка при чтении: {exc}",
            reply_markup=delete_this_msg(),
        )
    else:
        await msg.answer("✅ Переводы успешно обновлены.",
                         reply_markup=delete_this_msg())

    await state.clear()


# ---------------------------- СЛУЖЕБНЫЕ  UTILS ----------------------------- #


@dp.message(Command("chat_id"), IsAdmin())
async def cmd_show_chat_id(msg: types.Message) -> None:
    """Выводит текущий chat_id (удобно при отладке)."""
    await msg.answer(str(msg.chat.id), reply_markup=delete_this_msg())


# ------------------------------- /import ----------------------------------- #


@dp.message(Command("import"), AllowedIDs())
async def cmd_import(msg: types.Message, state: FSMContext) -> None:
    """Старт импорта: предлагаем выбрать файл из списка."""
    await state.clear()
    await msg.answer(
        "Выберите файл для просмотра/замены:",
        reply_markup=get_import_files_kb(),
    )


@dp.callback_query(F.data.startswith("import_get:"), AllowedIDs())
async def import_get_file(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Отправляем выбранный файл и переходим в режим ожидания нового."""
    name: str = cb.data.split(":", 1)[1]
    path: Optional[Path] = IMPORT_FILES.get(name)

    if not path or not path.exists():
        await cb.answer("Файл не найден 🚫", show_alert=True)
        return

    # 1) отдать текущую версию
    await bot.send_document(cb.from_user.id, FSInputFile(path))

    # translations.xlsx обновляется через отдельную команду
    if name == "translations.xlsx":
        await cb.message.answer(
            "Для обновления файла translations.xlsx используйте команду /reload_cand"
        )
        await cb.answer()
        return

    # 2) перейти к ожиданию нового файла
    await state.update_data(file_name=name)
    await state.set_state(ImportFSM.waiting_for_file)
    await cb.message.answer(
        f"📥 Отправьте новый файл для <b>{name}</b>, чтобы заменить текущий.\n\n"
        "Используйте структуру текущего файла.",
        parse_mode="HTML",
        reply_markup=delete_this_msg(),
    )
    await cb.answer()


@dp.callback_query(F.data == "import_cancel", AllowedIDs())
async def import_cancel(cb: types.CallbackQuery, state: FSMContext) -> None:
    """Отмена процесса импорта."""
    await state.clear()
    await cb.message.delete()
    await cb.answer("Импорт отменён.")


@dp.message(ImportFSM.waiting_for_file, AllowedIDs(), lambda m: m.document)
async def import_replace_file(msg: types.Message, state: FSMContext) -> None:
    """
    Получили документ → сохраняем и при необходимости перезагружаем
    вспомогательные кэши/индексы.
    """
    data = await state.get_data()
    name: Optional[str] = data.get("file_name")
    path: Optional[Path] = IMPORT_FILES.get(name)

    if not (name and path):
        await msg.answer("Контекст утерян. Запустите /import заново.")
        await state.clear()
        return

    backup: Path = path.with_suffix(path.suffix + ".bak")
    try:
        if path.exists():
            shutil.copy2(path, backup)

        await bot.download(msg.document.file_id, path)
    except Exception as exc:
        # восстановить из бэкапа, если был
        if backup.exists():
            shutil.copy2(backup, path)
        await msg.answer(f"⚠️ Ошибка при сохранении: {exc}")
        await state.clear()
        return
    finally:
        backup.unlink(missing_ok=True)

    # ─── дополнительные действия в зависимости от имени ───
    match name:
        case "countries.xlsx":
            from user.registration.utils.countries import load_countries
            load_countries()
        case "info.xlsx":
            from user.registration.utils.info import load_info
            load_info()
        case "info_for_rag.xlsx":
            from user.registration.utils.index_faq_local import build_faiss_index
            build_faiss_index()
        case "users.xlsx":
            from admins.superadmin.utils.import_excel import import_excel_users
            import_excel_users()
        case "texts_part.xlsx":
            from user.auth.translations_loader import load_reg_translations
            load_reg_translations()
        case "practice_supervisor.xlsx":
            from admins.practice_supervisor.registration.load_supervisor import (
                load_practice_supervisors,
            )
            load_practice_supervisors()

    await msg.answer(
        f"✅ Файл <b>{name}</b> успешно обновлён.",
        parse_mode="HTML",
        reply_markup=delete_this_msg(),
    )
    await state.clear()


# ----------------------------- RESTART БОТА ------------------------------- #


@dp.message(Command("restart"), AllowedIDs())
async def cmd_restart(msg: types.Message) -> None:
    """
    Перезапускает текущий процесс Python.
    Предполагается, что сервис-менеджер (systemd/pm2/supervisor) поднимет
    экземпляр заново.
    """
    await msg.answer("♻️ Перезапускаю бота...")
    asyncio.create_task(_do_restart())


async def _do_restart() -> None:
    await asyncio.sleep(1)  # дать Telegram время отправить сообщение
    os.execv(sys.executable, [sys.executable, *sys.argv])
