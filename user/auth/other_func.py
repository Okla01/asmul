from datetime import date, datetime
from typing import List, Dict

from PIL import Image
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram_dialog import DialogManager, Window, Dialog
from aiogram_dialog.widgets.kbd import Calendar
from aiogram_dialog.widgets.text import Const

from db.database import get_reg_translation
from user.auth.keyboards import SUBMIT_CALLBACK, BACK_CALLBACK
from user.auth.states import AbsenceCal, AbsenceFlow

LOC_HUMAN = {
    "lectures": "Лекции",
    "foreign_lang": "Интеграционная программа",
    "russian_lang": "Русский язык",
    "events": "Мероприятия",
    "work": "Работа",
}

REASON_HUMAN = {
    "illness": "Болезнь",
    "family": "Семейные обстоятельства",
    "vacation": "Отпуск",
    "other": "Другое",
}


def create_collage(images: List[Image.Image], cols: int, rows: int) -> Image.Image:
    """
    Создаем коллаж из списка PIL-изображений. Сетка cols×rows.
    Каждое изображение:
      - Подгоняем через thumbnail(...) для сохранения пропорций.
      - Центрируем в ячейке (на белом фоне).
    """
    thumb_w, thumb_h = 400, 400
    collage_w = cols * thumb_w
    collage_h = rows * thumb_h

    # Белый фон
    collage = Image.new('RGB', (collage_w, collage_h), (255, 255, 255))

    idx = 0
    for r in range(rows):
        for c in range(cols):
            if idx < len(images):
                img = images[idx]
                img.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)

                # Координаты верхнего левого угла ячейки
                x = c * thumb_w
                y = r * thumb_h

                # Чтобы центрировать изображение в этой ячейке:
                offset_x = x + (thumb_w - img.width) // 2
                offset_y = y + (thumb_h - img.height) // 2

                collage.paste(img, (offset_x, offset_y))
                idx += 1
    return collage


async def on_start_selected(
        c: CallbackQuery, widget: Calendar, manager: DialogManager, selected_date: date):
    manager.dialog_data["start"] = selected_date  # сохраняем
    await manager.switch_to(AbsenceCal.End)


async def on_end_selected(
        c: CallbackQuery, widget: Calendar, manager: DialogManager, selected_date: date):
    # внешний FSM, переданный через data
    absence_fsm: FSMContext = manager.start_data["parent_fsm"]

    # сохраняем даты в FSM отсутствия
    start_day = manager.dialog_data.get("start")
    await absence_fsm.update_data(dates={
        "start": str(start_day),
        "end": str(selected_date)
    })

    # соберём данные для текста
    data = await absence_fsm.get_data()
    human_loc = ", ".join(LOC_HUMAN.get(l, l) for l in data.get("locations", [])) or "—"
    reason_code = data.get("reason_code")
    human_reason = REASON_HUMAN.get(reason_code, "—")

    dates_str = f"с {start_day.strftime('%d.%m.%Y')} до {selected_date.strftime('%d.%m.%Y')}"
    comment = data.get("add_comment") or "—"

    text = (
        "🔎 <b>Проверьте данные и подтвердите отправку:</b>\n\n"
        f"<b>Место(а):</b> {human_loc}\n"
        f"<b>Причина:</b> {human_reason}\n"
        f"<b>Период:</b> {dates_str}\n"
        f"<b>Комментарий:</b> {comment}\n"
        "<b>Прикрепленные документы:</b>"
    )

    # переводим основной FSM в состояние подтверждения
    await absence_fsm.set_state(AbsenceFlow.ConfirmingDetails)
    await manager.done()  # закрываем диалог‑календарь

    await c.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Утвердить", callback_data=SUBMIT_CALLBACK)],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=BACK_CALLBACK)],
        ]),
        parse_mode="HTML"
    )
    files = data.get("files", [])
    preview_ids: list[int] = []
    for ftype, file_id, filename in files:
        if ftype == "doc":
            sent = await c.message.answer_document(file_id, caption=filename or "")
        else:  # photo
            sent = await c.message.answer_photo(file_id)
        preview_ids.append(sent.message_id)

    # сохраняем id присланных сообщений, чтобы потом удалить
    await absence_fsm.update_data(preview_msg_ids=preview_ids)


start_win = Window(
    Const("🗓 Выберите <b>день начала</b> отсутствия:"),
    Calendar(id="start_cal", on_click=on_start_selected),
    state=AbsenceCal.Start,
    parse_mode="HTML"
)

end_win = Window(
    Const("🗓 Выберите <b>день окончания</b> отсутствия:"),
    Calendar(id="end_cal", on_click=on_end_selected),
    state=AbsenceCal.End,
    parse_mode="HTML"
)

absence_calendar_dialog = Dialog(start_win, end_win)


def build_user_card_text(card: Dict[str, any]) -> str:
    """
    Формирует caption для участницы. Ни БД, ни Telegram здесь не трогаем —
    только превращаем словарь в HTML-текст.
    """
    program_name = card.get("program", "Не указано")
    status = card.get("status", "")
    # дефолты -- на случай, если колонок нет в SELECT
    card.setdefault("current_doop", "N/A")
    card.setdefault("minor_violations", "0")
    card.setdefault("medium_violations", "0")
    card.setdefault("serious_violations", "0")
    card.setdefault("commendations_count", "0")
    card.setdefault("commendation_reason", "Нет")

    lines: List[str] = [
        f"<b>ФИО:</b> {card.get('full_name', 'Не указано')}",
        f"<b>Программа:</b> {program_name}",
        f"<b>Страна:</b> {card.get('country', 'Не указано')}",
        f"<b>Тик:</b> {card.get('tik', 'Не указано')}",
        f"<b>Статус:</b> {status if status else 'Не указано'}",
        f"<b>Подразделение:</b> {card.get('department', 'Не указано')}",
        f"<b>Место работы:</b> {card.get('workplace', 'Не указано')}",
        f"<b>Модуль:</b> {card.get('module', 'Не указано')}",
        f"<b>Должность:</b> {card.get('position', 'Не указано')}",
        f"<b>Руководитель:</b> {card.get('supervisor_name', 'Не указано')}",
        "\n<b>Общий рейтинг:</b>",
        f"  Коэфф. эффективности: {card.get('efficiency_coefficient', 'N/A')}%",
    ]

    if "мир" in program_name.lower():
        lines += [
            f"  Средний KPI: {card.get('average_kpi', 'N/A')}%",
            f"  Средний Русс. яз: {card.get('average_russian_score', 'N/A')}%",
        ]

    lines += [
        f"  Средний Инт.П.: {card.get('average_int_p', 'N/A')}%",
        f"  Текущий ДООП: {card.get('current_doop')}%",
    ]

    if "мир" in program_name.lower():
        lines.append(f"  AS: {card.get('as_score', 'N/A')}")

    lines += [
        f"  BCats: {card.get('bcats', 'N/A')}",
        f"  ЗКА: {card.get('zka', 'N/A')}",
        f"  ЗКО: {card.get('zko', 'N/A')}",
        f"\n<b>Дисциплина: ({card.get('discipline_score', 'N/A')})</b>",
        f"  Лёгкие нарушения: {card.get('minor_violations')}",
        f"  Средние нарушения: {card.get('medium_violations')}",
        f"  Тяжёлые нарушения: {card.get('serious_violations')}",
        f"  Комментарий: {card.get('discipline_comment')}",
        f"\n<b>Поощрения:</b> {card.get('encouragement_score')}",
        f"  <b>Комментарий:</b> {card.get('encouragement_comment')}",
    ]
    try:
        if ("исключена" or "уволена") in status.lower():
            lines.append(
                f"\n⚠️ <b>Причина увольнения:</b> {card.get('exclusion_reason', 'Не указана')}"
            )
    except:
        pass

    return "\n".join(lines)


def is_event_open(ev: dict) -> bool:
    """
    Событие открыто, если:
      • status='active'
      • дедлайн отсутствует ИЛИ ещё не прошёл
    """
    if ev["status"] != "active":
        return False
    dl = ev["report_deadline"]
    if not dl:
        return True
    try:
        return datetime.now() <= datetime.strptime(dl, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return False


def trp(key: str, **kwargs) -> str:
    """
    Аналог tr(...) для зарегистрированного пользователя.
    Здесь не берутся во внимание языковые настройки (только один язык).
    """
    text_template = get_reg_translation(key)
    try:
        return text_template.format(**kwargs)
    except Exception:
        # В случае, если шаблон .format(**kwargs) не может быть применён — вернуть без форматирования
        return text_template


