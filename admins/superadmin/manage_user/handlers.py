"""
Модуль обработчиков панели суперадмина Telegram‑бота на базе aiogram.

Задачи модуля:
1. Отображение главного меню суперадмина.
2. Управление списком администраторов (назначение/снятие ролей, блокировка/разблокировка).
3. Управление обычными пользователями (поиск, блокировка/разблокировка).
4. Реализация inline‑поиска пользователей по ФИО, @username или роли.
5. Управление ролями и блокировкой через инлайн‑кнопки.

‼️  ВАЖНО: Все изменения носят исключительно документирующий характер.
     Логика работы и структура исходного кода сохранены без изменений.
"""

# ────────────────────────────
#           ИМПОРТЫ
# ────────────────────────────
#   aiogram — асинхронный фреймворк для Telegram‑ботов
from aiogram import F, types
from aiogram.fsm.context import FSMContext  # Контекст конечного автомата состояний
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent  # Результаты для inline‑mode

#   Локальные модули проекта
from admins.keyboards import get_superadmin_panel_kb  # Клавиатура главного меню суперадмина
from config import dp, bot, ROLES  # Объекты диспетчера/бота и справочник ролей
from db.database import (
    get_user_role, set_user_role,      # Получение/изменение роли пользователя
    block_user, unblock_user,          # Блокировка/разблокировка пользователя
    search_users_by_fio,               # Поиск пользователей (ФИО/@username/роль)
    _is_blocked,                       # Проверка: пользователь заблокирован?
    _build_card_text_edit_role         # Формирование текста карточки пользователя
)
from admins.filters.is_admin import IsAdmin  # Кастомный фильтр «является админом»

from admins.superadmin.manage_user.states import SupAdmUserManage  # Состояния FSM панели суперадмина
from admins.superadmin.manage_user.keyboards import sa_manage_entry_kb, sa_user_kb  # Клавиатуры панели


# ────────────────────────────
#  ОБРАБОТЧИК: главное меню
# ────────────────────────────
@dp.callback_query(F.data.startswith("sa_main_menu"), IsAdmin())
async def sa_main_menu_h(cb: types.CallbackQuery):
    """Показать главное меню панели суперадмина."""
    await cb.message.edit_text("Панель суперадмина", reply_markup=get_superadmin_panel_kb())


# ────────────────────────────
#        УПРАВЛЕНИЕ АДМИНАМИ
# ────────────────────────────
@dp.callback_query(F.data == "sa_admins", IsAdmin())
async def sa_manage_admins(cb: types.CallbackQuery, state: FSMContext):
    """Точка входа в подраздел «Администраторы».
    Передаёт управление обобщённой функции _entry_generic с параметрами режима «admins»."""
    await _entry_generic(cb, state, mode="admins", label="администратора")


# ────────────────────────────
#      УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ
# ────────────────────────────
@dp.callback_query(F.data == "sa_peoples", IsAdmin())
async def sa_manage_users(cb: types.CallbackQuery, state: FSMContext):
    """Точка входа в подраздел «Пользователи».
    Передаёт управление _entry_generic с режимом «users»."""
    await _entry_generic(cb, state, mode="users", label="пользователя")


# ────────────────────────────
#   ОБЩАЯ ТОЧКА ВХОДА ДЛЯ РАЗДЕЛОВ
# ────────────────────────────
async def _entry_generic(
    cb: types.CallbackQuery,
    state: FSMContext,
    mode: str,
    label: str
):
    """Подготовка и отображение экрана поиска пользователей/администраторов.

    :param cb:            Объект callback‑запроса.
    :param state:         Контекст FSM.
    :param mode:          "admins" или "users" — определяет фильтрацию результатов.
    :param label:         Человекочитаемое слово для подсказки ("администратора" / "пользователя").
    """
    # ⛔️  Проверка: инициатор ДОЛЖЕН быть суперадмином, иначе выходим без ответа.
    if get_user_role(cb.from_user.id) != "admin_supervisor":
        return

    # 1. Сброс FSM
    await state.clear()

    # 2. Устанавливаем новое состояние ожидания ввода для inline‑поиска
    await state.set_state(SupAdmUserManage.AwaitUserSearch)

    # 3. Сохраняем в состоянии данные, необходимые для последующей логики
    await state.update_data(
        prompt_msg_id=cb.message.message_id,  # ID сообщения‑подсказки, чтобы позже его отредактировать
        mode=mode                            # Режим работы (admins/users)
    )

    # 4. Редактируем сообщение, показываем инструкцию и клавиатуру
    await cb.message.edit_text(
        f"Нажмите «Найти {label}» и начните вводить ФИО, @username или роль.",
        reply_markup=sa_manage_entry_kb(label)
    )
    # 5. Закрываем всплывающее окно «загрузка» Telegram
    await cb.answer()


# ────────────────────────────
#         INLINE‑ПОИСК
# ────────────────────────────
@dp.inline_query(SupAdmUserManage.AwaitUserSearch, IsAdmin())
async def sa_inline_search(query: types.InlineQuery, state: FSMContext):
    """Inline‑обработчик для поиска пользователей во время набора текста.

    Работает ТОЛЬКО в состоянии SupAdmUserManage.AwaitUserSearch, то есть после
    вызова _entry_generic. Возвращает до 25 найденных пользователей.
    """
    text: str = query.query.strip()  # Очищаем пробелы вокруг запроса

    # ── Удаляем префикс «su:» / «SU:», если пользователь использует сокращение
    if text.lower().startswith("su:"):
        text = text[3:].lstrip()

    # Определяем текущий режим панели (admins/users) из FSM
    mode: str = (await state.get_data())["mode"]

    # Базовый поиск по БД (возвращает словарь пользователей)
    users = search_users_by_fio(text, limit=25)

    # ── Внутренняя функция для фильтрации пользователей по режиму
    def _allowed(uid: int) -> bool:
        role: str | None = get_user_role(uid)
        # Если режим «admins» → показываем только админов (кроме суперадминов)
        if mode == "admins":
            return role is not None and role.startswith("admin_") and role != "admin_supervisor"
        # Если режим «users» → скрываем всех админов, т.е. оставляем обычных пользователей
        return role is not None and not role.startswith("admin_")

    # Применяем фильтрацию
    users = [u for u in users if _allowed(u["id"])]

    # ── Формируем результаты для inline‑ответа
    results: list[InlineQueryResultArticle] = [
        InlineQueryResultArticle(
            id=str(u["id"]),
            title="Не указано" if u["full_name"] is None else str(u["full_name"]),
            description=f"Роль: {ROLES.get(get_user_role(u['id']), '—')}",
            input_message_content=InputTextMessageContent(message_text=f"#SU{u['id']}")
        )
        for u in users
    ]

    # Отправляем результаты. cache_time=1 → кэш почти отсутствует, чтобы списки были свежими
    await query.answer(results, cache_time=1)


# ────────────────────────────
#      ОБРАБОТКА ВЫБОРА #SU<ID>
# ────────────────────────────
@dp.message(SupAdmUserManage.AwaitUserSearch, F.text.startswith("#SU"), IsAdmin())
async def sa_user_selected(msg: types.Message, state: FSMContext):
    """Пользователь нажал на результат inline‑поиска (#SU<ID>). Загружаем карточку."""
    # 1. Получаем ID из текста (после префикса «#SU»)
    try:
        uid: int = int(msg.text[3:])
    except ValueError:
        # Невалидный формат → игнорируем
        return

    # 2. Проверяем, существует ли пользователь и его роль
    role: str | None = get_user_role(uid)
    if role is None:
        await msg.answer("❗️ Пользователь не найден.")
        return

    # 3. Извлекаем дополнительную информацию из FSM
    data = await state.get_data()
    mode = data["mode"]
    blocked: bool = _is_blocked(uid)

    # 4. Генерируем клавиатуру и текст карточки
    kb = sa_user_kb(uid, role, blocked, mode)
    text = _build_card_text_edit_role(uid, role, blocked)

    # 5. Редактируем исходное «приглашение к поиску» сообщением карточкой пользователя
    prompt_msg_id = data["prompt_msg_id"]
    await bot.edit_message_text(
        chat_id=msg.chat.id,
        message_id=prompt_msg_id,
        text=text,
        parse_mode="HTML",
        reply_markup=kb
    )

    # 6. Удаляем сервисное сообщение «#SU<ID>»
    await msg.delete()

    # 7. Переводим FSM в состояние AwaitAction (ожидание действий с выбранным пользователем)
    await state.set_state(SupAdmUserManage.AwaitAction)


# ────────────────────────────
#         СМЕНА РОЛИ
# ────────────────────────────
@dp.callback_query(F.data.startswith("sa_setrole:"), IsAdmin())
async def sa_set_role(cb: types.CallbackQuery, state: FSMContext):
    """Обработчик кнопки «Изменить роль» внутри карточки пользователя."""
    # Разбираем данные callback‑запроса: «sa_setrole:<uid>:<new_role>»
    _, uid_str, new_role = cb.data.split(":")
    uid = int(uid_str)

    cur_role = get_user_role(uid)

    # 1. Если роль уже совпадает — сообщаем и выходим
    if cur_role == new_role:
        await cb.answer("Эта роль уже выбрана ✅", show_alert=True)
        return

    # 2. Защита от изменения роли другого суперадмина
    if cur_role == "admin_supervisor" and uid != cb.from_user.id:
        await cb.answer("Невозможно изменить роль другого суперадмина.", show_alert=True)
        return

    # 3. Записываем новую роль в БД
    set_user_role(uid, new_role)

    # 4. Обновляем карточку: текст + клавиатура
    blocked = _is_blocked(uid)
    kb = sa_user_kb(uid, new_role, blocked, (await state.get_data())["mode"])
    text = _build_card_text_edit_role(uid, new_role, blocked)

    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

    # 5. Показываем всплывающее подтверждение
    await cb.answer("✅ Роль успешно изменена!")


# ────────────────────────────
#         БЛОКИРОВКА
# ────────────────────────────
@dp.callback_query(F.data.startswith("sa_block:"), IsAdmin())
async def sa_block_user(cb: types.CallbackQuery, state: FSMContext):
    """Обработчик кнопки «Заблокировать пользователя»."""
    uid = int(cb.data.split(":")[1])
    role = get_user_role(uid)

    # Защита: нельзя заблокировать другого суперадмина
    if role == "admin_supervisor" and uid != cb.from_user.id:
        await cb.answer("Невозможно заблокировать другого суперадмина.", show_alert=True)
        return

    # 1. Блокируем пользователя в БД
    block_user(uid)

    # 2. Обновляем интерфейс
    kb = sa_user_kb(uid, role, True, (await state.get_data())["mode"])
    text = _build_card_text_edit_role(uid, role, True)

    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await cb.answer("🚫 Пользователь заблокирован!")


# ────────────────────────────
#        РАЗБЛОКИРОВКА
# ────────────────────────────
@dp.callback_query(F.data.startswith("sa_unblock:"), IsAdmin())
async def sa_unblock_user(cb: types.CallbackQuery, state: FSMContext):
    """Обработчик кнопки «Разблокировать пользователя»."""
    uid = int(cb.data.split(":")[1])

    # Пробуем снять блокировку. В блок try/except, т.к. БД может вернуть ошибку
    try:
        unblock_user(uid)
    except Exception:
        await cb.answer("Не удалось изменить статус пользователя. Попробуйте снова.", show_alert=True)
        return

    # 1. Получаем актуальную роль (на случай, если она ранее изменилась)
    role = get_user_role(uid)

    # 2. Обновляем карточку: клавиатуру и текст
    kb = sa_user_kb(uid, role, False, (await state.get_data())["mode"])
    text = _build_card_text_edit_role(uid, role, False)

    await cb.message.edit_text(text=text, reply_markup=kb, parse_mode="HTML")
    await cb.answer("✅ Пользователь разблокирован!")
