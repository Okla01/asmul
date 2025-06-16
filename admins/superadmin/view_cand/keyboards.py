"""
Модуль `keyboards.py` — вспомогательные inline‑клавиатуры раздела «Участницы».

Содержит две функции:
1. `entry_kb()`  — клавиатура начального экрана (поиск + выход в меню).
2. `card_kb()`   — клавиатура карточки участницы (назад / меню).

Клавиатуры строятся через `InlineKeyboardBuilder` для гибкой компоновки.
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ──────────────────────────────────────────────────────────────────────────
# 1. Клавиатура «🔍 Найти участницу / 🏠 В меню»
# ──────────────────────────────────────────────────────────────────────────
def entry_kb() -> InlineKeyboardMarkup:
    """Возвращает клавиатуру для экрана поиска.

    • Первая кнопка `switch_inline_query_current_chat` — открывает inline‑режим с
      предзаполненным префиксом `ps: ` (Telegram сразу фокусирует поле ввода).
    • Вторая кнопка — возврат «🏠 В меню» (callback‑data `a_menu` уже обрабатывается глобально).
    """
    kb = InlineKeyboardBuilder()

    # 🔍 Кнопка для inline‑поиска (в текущем чате), префикс «ps: » + пробел даёт подсказку
    kb.button(text="🔍 Найти участницу", switch_inline_query_current_chat="ps: ")

    # 🏠  Назад в меню
    kb.button(text="🏠 В меню", callback_data="a_menu")

    # adjust(1) → каждая кнопка в своей строке
    return kb.adjust(1).as_markup()


# ──────────────────────────────────────────────────────────────────────────
# 2. Клавиатура карточки участницы (↩️ Назад / 🏠 Меню)
# ──────────────────────────────────────────────────────────────────────────
def card_kb() -> InlineKeyboardMarkup:
    """Возвращает клавиатуру под карточкой участницы.

    • `↩️ Назад` → callback `p_participants` (должен обрабатываться в модуле‑родителе).
    • `🏠 В меню` → callback `a_menu` (глобальный возврат в главное меню).
    """
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="↩️ Назад", callback_data="p_participants"),
        InlineKeyboardButton(text="🏠 В меню", callback_data="a_menu"),
    )
    return kb.as_markup()
