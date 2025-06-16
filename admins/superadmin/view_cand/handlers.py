"""
Модуль `handlers.py` — обработчики раздела «Участницы» в панели суперадмина.

Функциональность:
1. Открыть поиск участниц по кнопке «Участницы» в главном меню.
2. Реализовать inline‑поиск по ФИО / username (префикс `ps:`).
3. Показать карточку участницы с фото и данными выбранного цикла.
4. Просмотр карточек разных циклов через callback‑кнопки.
5. Возврат в главное меню «Панель суперадмина».

‼️  Изменения носят чисто документирующий характер — добавлены подробные комментарии.
"""

# ────────────────────────────
#           ИМПОРТЫ
# ────────────────────────────
# ⚙️  aiogram
from aiogram import F, types                              # F — фильтры, types — объекты Telegram API
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext                 # Контекст для FSM (Finite‑State Machine)
from aiogram.types import (
    InlineQueryResultArticle, InputTextMessageContent,
    InputMediaPhoto,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# 🏠 Модули проекта
from admins.filters.is_admin import IsAdmin                # Фильтр «проверка прав администратора»
from admins.superadmin.view_cand.states import PSearch     # Состояния FSM раздела «Участницы»
from admins.superadmin.view_cand.keyboards import entry_kb, card_kb  # Клавиатуры текущего раздела
from admins.utils import build_admin_card_text             # Формирование текста карточки участницы
from db.database import (
    get_participant_card,      # Получить словарь данных участницы (по ID и циклу)
    get_photo_or_none,         # Вернуть bytes‑объект фото или None, если нет
    search_users_by_fio,       # Поиск пользователей по ФИО/username/…
)
from config import dp, bot                                 # Диспетчер и Bot из aiogram


# ──────────────────────────────────────────────────────────────────────────
# 1. Кнопка «Участницы» в главном меню суперадмина
# ──────────────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "sa_participants", IsAdmin())
async def p_open_search(cb: types.CallbackQuery, state: FSMContext):
    """Открывает экран поиска участниц.

    • Переводит FSM в состояние `WaitingInline`.
    • Сохраняет ID сообщения‑подсказки (чтобы потом заменить карточкой).
    • Редактирует текст + выводит клавиатуру с кнопкой «🔍 Найти участницу».
    """
    # 1️⃣  Сохраняем состояние
    await state.set_state(PSearch.WaitingInline)
    await state.update_data(prompt_msg_id=cb.message.message_id)

    # 2️⃣  Обновляем сообщение
    await cb.message.edit_text(
        "Нажмите «Найти участницу» и начните вводить ФИО / username.\n"
        "Выберите нужную из выпадающего списка.",
        reply_markup=entry_kb(),
    )
    await cb.answer()  # Закрываем «часики»


# ──────────────────────────────────────────────────────────────────────────
# 2. Inline‑поиск по участницам (работает в состоянии WaitingInline)
# ──────────────────────────────────────────────────────────────────────────
@dp.inline_query(PSearch.WaitingInline, IsAdmin())
async def p_inline_search(query: types.InlineQuery):
    """Обработчик inline‑запроса «ps: …».

    • Срезает необязательный префикс `ps:`.
    • Игнорирует запросы короче 2 символов (уменьшаем бесполезный трафик).
    • Возвращает до 25 результатов в формате `InlineQueryResultArticle`.
    • При отсутствии результатов показывает inline‑хинт «Не найдено».
    """
    text = query.query.lstrip()

    # Убираем префикс «ps:» (регистр неважен)
    if text.lower().startswith("ps:"):
        text = text[3:].lstrip()

    # Минимум 2 символа, иначе Telegram откажется показывать (и зря грузить БД)
    if len(text) < 2:
        return await query.answer([], cache_time=1)

    # Ищем только пользователей‑НЕ‑ботов (is_bot_user=False)
    users = search_users_by_fio(text, limit=25, is_bot_user=False)
    if not users:
        return await query.answer(
            [], cache_time=1,
            switch_pm_text="Не найдено", switch_pm_parameter="ps_not_found",
        )

    # Формируем результаты для Telegram (id должен быть str)
    results = [
        InlineQueryResultArticle(
            id=str(u["id"]),
            title=u["full_name"],
            description=f"Тик: {u.get('tik', '–')}",
            input_message_content=InputTextMessageContent(message_text=f"#PID{u['id']}")
        )
        for u in users
    ]
    await query.answer(results, cache_time=1)


# ──────────────────────────────────────────────────────────────────────────
# 3. Пользователь выбрал результат (#PID<ID>)
# ──────────────────────────────────────────────────────────────────────────
@dp.message(PSearch.WaitingInline, F.text.startswith("#PID"), IsAdmin())
async def p_show_card(msg: types.Message, state: FSMContext):
    """Показывает карточку участницы.

    Шаги:
    1. Парсим ID из сообщения вида «#PID123».
    2. Получаем данные участницы (`get_participant_card`).
    3. Строим текст карточки + клавиатуру `card_kb()`.
    4. Пытаемся заменить исходное сообщение‑подсказку карточкой (с фото или без).
       Если редактирование невозможно (старое сообщение слишком древнее, удалено и т.д.) —
       отправляем новое сообщение.
    5. Удаляем «служебное» сообщение с #PID.
    """
    # 1️⃣  Извлекаем ID участницы из текста «#PID…»
    try:
        uid = int(msg.text[4:])
    except ValueError:
        return  # неправильный формат

    # 2️⃣  Достаём данные
    card = get_participant_card(uid)
    if not card:
        await msg.answer("❗️ Не удалось загрузить данные участницы")
        return

    # 3️⃣  Формируем вывод
    caption = build_admin_card_text(card)
    kb = card_kb()
    photo = get_photo_or_none(card)  # bytes | None

    # 4️⃣  Меняем исходное сообщение, если возможно
    prompt_id = (await state.get_data()).get("prompt_msg_id")

    try:
        if prompt_id and photo:
            # Заменяем текст + фото магией edit_message_media()
            await bot.edit_message_media(
                chat_id=msg.chat.id,
                message_id=prompt_id,
                media=InputMediaPhoto(media=photo, caption=caption, parse_mode="HTML"),
                reply_markup=kb,
            )
        elif prompt_id:
            # Только текст
            await bot.edit_message_text(
                chat_id=msg.chat.id, message_id=prompt_id,
                text=caption, parse_mode="HTML", reply_markup=kb,
            )
        else:
            raise TelegramBadRequest("no prompt_id")
    except TelegramBadRequest:
        # 👉  Отправляем новое сообщение, если редактирование не удалось (например, канал?)
        if photo:
            await bot.send_photo(
                chat_id=msg.chat.id, photo=photo,
                caption=caption, parse_mode="HTML", reply_markup=kb,
            )
        else:
            await msg.answer(caption, parse_mode="HTML", reply_markup=kb)
    except TelegramAPIError as e:
        # Логируем, но всё равно пытаемся ответить текстом
        print(f"[participants] TG error: {e}")
        await msg.answer(caption, parse_mode="HTML", reply_markup=kb)

    # 5️⃣  Удаляем служебное сообщение #PID…, чтобы чат был чистый
    try:
        await msg.delete()
    except TelegramAPIError:
        pass  # если уже нет — не критично


# ──────────────────────────────────────────────────────────────────────────
# 4. Переключение карточки на другой «цикл» (год программы)
# ──────────────────────────────────────────────────────────────────────────
@dp.callback_query(F.data.startswith("pcard:"), IsAdmin())
async def p_show_cycle(cb: types.CallbackQuery):
    """Показывает данные участницы в выбранном цикле (годе программы)."""
    _, uid, cyc = cb.data.split(":")  # pcard:<uid>:<cycle>
    uid, cyc = int(uid), int(cyc)

    # Получаем данные + подменяем цикл
    card = get_participant_card(uid)
    if not card:
        await cb.answer("Не удалось загрузить данные", show_alert=True)
        return

    card["cycle"] = cyc

    caption = build_admin_card_text(card)

    # Упрощённая клавиатура: только «🏠 В меню»
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 В меню", callback_data="a_menu")
    kb = kb.adjust(1).as_markup()

    photo = get_photo_or_none(card)
    try:
        if photo:
            await cb.message.edit_caption(caption=caption, parse_mode="HTML", reply_markup=kb)
        else:
            await cb.message.edit_text(text=caption, parse_mode="HTML", reply_markup=kb)
    except TelegramAPIError:
        # Случай, если сообщение «не изменилось»
        await cb.message.answer(caption, parse_mode="HTML", reply_markup=kb)

    await cb.answer()


# ──────────────────────────────────────────────────────────────────────────
# 5. Кнопка «🏠 В меню»
# ──────────────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "a_menu", IsAdmin())
async def p_back_to_menu(cb: types.CallbackQuery):
    """Возврат в главное меню панели суперадмина."""
    # Ленивая импорт‑защита от циклов
    from admins.keyboards import get_superadmin_panel_kb

    try:
        await cb.message.edit_text("Панель суперадмина:", reply_markup=get_superadmin_panel_kb())
        await cb.answer()
    except TelegramAPIError:
        # Если не можем редактировать (например, не наше сообщение) — отправляем новое и удаляем старое
        await cb.message.answer("Панель суперадмина:", reply_markup=get_superadmin_panel_kb())
        await cb.message.delete()
