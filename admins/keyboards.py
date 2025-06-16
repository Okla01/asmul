"""
Инлайн-клавиатуры для админского блока.

Все функции возвращают **готовый** `InlineKeyboardMarkup`, поэтому
их можно сразу передавать в `reply_markup=...`.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import IMPORT_FILES, ROLES

# --------------------------------------------------------------------------- #
#                       ПАНЕЛИ ДЛЯ РАЗНЫХ ТИПОВ РОЛЕЙ                         #
# --------------------------------------------------------------------------- #


def get_practice_supervisor_panel_kb() -> InlineKeyboardMarkup:
    """Кнопки Руководителя практики."""
    return (
        InlineKeyboardBuilder()
        .button(text="FAQ", callback_data="p_faq")
        .button(text="ОС по участнице", callback_data="p_os")
        .button(text="Информация об участницах", callback_data="p_participants")
        .button(text="Задать вопрос", callback_data="p_ask")
        .adjust(1)
        .as_markup()
    )


def get_admin_panel_kb() -> InlineKeyboardMarkup:
    """Кнопки обычного администратора."""
    return (
        InlineKeyboardBuilder()
        .button(text="FAQ", callback_data="a_faq")
        .button(text="Информация об участницах", callback_data="a_participants")
        .button(text="Задать вопрос", callback_data="a_ask")
        .adjust(1)
        .as_markup()
    )


def get_superadmin_panel_kb() -> InlineKeyboardMarkup:
    """Кнопки суперадмина (полный доступ)."""
    return (
        InlineKeyboardBuilder()
        .button(text="Управление администраторами", callback_data="sa_admins")
        .button(text="Управление пользователями", callback_data="sa_peoples")
        .button(text="Создать рассылку", callback_data="sa_mailing")
        .button(text="Управление FAQ", callback_data="sa_faq")
        .button(text="Управление мероприятиями", callback_data="sa_events")
        .button(text="Экспорт отчётов", callback_data="sa_export")
        .button(text="Информация об участницах", callback_data="sa_participants")
        .button(text="Отображение ОС", callback_data="sa_os_view")
        .button(text="Дисциплинарные нарушения", callback_data="sa_violations")
        .adjust(1)
        .as_markup()
    )


# --------------------------------------------------------------------------- #
#                        ВСПОМОГАТЕЛЬНЫЕ КЛАВИАТУРЫ                           #
# --------------------------------------------------------------------------- #


def _role_kb(current_role: str) -> InlineKeyboardMarkup:
    """
    Переключатель ролей.
    Текущая роль помечается галочкой, чтобы пользователь видел, что выбрано.
    """
    kb = InlineKeyboardBuilder()
    for code, title in ROLES.items():
        prefix = "✅ " if code == current_role else ""
        kb.button(text=f"{prefix}{title}", callback_data=f"setrole:{code}")

    kb.adjust(1)
    return kb.as_markup()


def delete_this_msg(with_state: bool = False) -> InlineKeyboardMarkup:
    """
    Однокнопочная клавиатура «Закрыть» — удаляет текущее сообщение.
    Параметр `with_state` позволяет сохранить / очистить FSM-состояние
    (используется в callback-хэндлере).
    """
    return (
        InlineKeyboardBuilder()
        .button(text="Закрыть", callback_data=f"delete_this_msg_admins_{with_state}")
        .as_markup()
    )


# --------------------------------------------------------------------------- #
#                               /import                                       #
# --------------------------------------------------------------------------- #


def get_import_files_kb() -> InlineKeyboardMarkup:
    """Список файлов, доступных для скачивания / замены."""
    kb = InlineKeyboardBuilder()
    for name in IMPORT_FILES:
        kb.button(text=name, callback_data=f"import_get:{name}")

    kb.button(text="🚫 Отмена", callback_data="import_cancel")
    kb.adjust(1)
    return kb.as_markup()


def import_cancel_kb() -> InlineKeyboardMarkup:
    """Отдельная клавиатура «Отмена» (если нужно без списка файлов)."""
    return (
        InlineKeyboardBuilder()
        .button(text="🚫 Отмена", callback_data="import_cancel")
        .as_markup()
    )
