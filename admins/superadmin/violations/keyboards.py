"""
keyboards_commented.py  — генераторы inline‑клавиатур, используемые
при фиксации нарушений.

Каждая функция возвращает `InlineKeyboardMarkup`, которую мы используем в
хендлерах (`handlers.py`). Для удобства:
    • названия функций отражают место применения;
    • каждое callback‑данное начинается с префикса `vio_`, чтобы избежать
      коллизий с другими подсистемами бота.

Обратите внимание: файл опирается на Excel‑таблицу `violations.xlsx`, которая
содержит шаблоны текстов нарушений.
"""

from pathlib import Path
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import Sequence, List
import pandas as pd

# --- индексы столбцов при разборе результатов pd.read_excel ---
I_ID, I_TITLE = 0, 1

# Путь к xlsx‑файлу с шаблонами
XL_PATH = Path(__file__).with_name("violations.xlsx")


# ────────────────────────────────────────────────────────────────────────────────
# Основная карточка участницы (кнопка «Выставить нарушение»)
# ────────────────────────────────────────────────────────────────────────────────
def main_card_kb(uid: int) -> InlineKeyboardMarkup:
    """
    Клавиатура для карточки участницы.

    • «Выставить нарушение»  — запускает сценарий фиксации (severity → …).
    • «Назад»                — возвращает в панель суперадмина.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="Выставить нарушение", callback_data=f"vio_start:{uid}")
    kb.button(text="Назад", callback_data="vio_back")
    return kb.adjust(1).as_markup()


# ────────────────────────────────────────────────────────────────────────────────
# Выбор тяжести нарушения
# ────────────────────────────────────────────────────────────────────────────────
def severity_kb() -> InlineKeyboardMarkup:
    """
    Показываем три возможных уровня тяжести + кнопку «Назад».
    Callback‑данные имеют вид `vio_s:<level>`.
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="Лёгкое", callback_data="vio_s:light")
    kb.button(text="Среднее", callback_data="vio_s:medium")
    kb.button(text="Тяжёлое", callback_data="vio_s:heavy")
    kb.button(text="Назад", callback_data="vio_back2card")
    return kb.adjust(1).as_markup()


# ────────────────────────────────────────────────────────────────────────────────
# Шаблоны описаний нарушений
# ────────────────────────────────────────────────────────────────────────────────
def template_kb(sev: str) -> InlineKeyboardMarkup:
    """
    Формирует список типовых описаний для выбранного уровня тяжести `sev`.

    Параметры
    ---------
    sev : str
        Один из {'light', 'medium', 'heavy'}.

    Логика
    ------
    1. Читаем рабочий Excel‑файл (`violations.xlsx`).
    2. Берём столбец, совпадающий с названием степени тяжести.
    3. Отбрасываем пустые ячейки (`dropna`).
    4. Для первых 64 символов шаблона создаём кнопку с callback
       `vio_tpl_idx:<index>`.
    5. Добавляем пункт «Другое» для ручного ввода.
    """
    df = pd.read_excel(XL_PATH)
    templates: List[str] = df[sev].dropna().tolist()

    kb = InlineKeyboardBuilder()
    for idx, txt in enumerate(templates, 0):
        kb.button(text=txt[:64], callback_data=f"vio_tpl_idx:{idx}")
    kb.button(text="Другое", callback_data="vio_tpl_idx:custom")
    kb.button(text="Назад", callback_data="vio_back2sev")
    return kb.adjust(1).as_markup()


# ────────────────────────────────────────────────────────────────────────────────
# Выбор даты нарушения (быстрые кнопки)
# ────────────────────────────────────────────────────────────────────────────────
def date_kb() -> InlineKeyboardMarkup:
    """
    Два варианта:
      • «Сегодня»   — берём текущую дату;
      • «Календарь» — открываем inline‑календарь для произвольной даты.

    Плюс «Назад».
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="Сегодня",      callback_data="vio_date:today")
    kb.button(text="📅 Календарь", callback_data="vio_date:cal")
    kb.button(text="Назад",        callback_data="vio_back2descr")
    return kb.adjust(1).as_markup()


# ────────────────────────────────────────────────────────────────────────────────
# Шаг «прикрепите файл» (единственная кнопка «Назад»)
# ────────────────────────────────────────────────────────────────────────────────
def attach_back_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Назад", callback_data="vio_back2date")
    return kb.adjust(1).as_markup()


# ────────────────────────────────────────────────────────────────────────────────
# Подтверждение сохранения
# ────────────────────────────────────────────────────────────────────────────────
def confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Подтвердить", callback_data="vio_save")
    kb.button(text="Назад", callback_data="vio_back2date")
    return kb.adjust(1).as_markup()
