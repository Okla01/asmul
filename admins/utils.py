"""
Вспомогательные функции, которые используются в разных частях админ-панели.

* `build_admin_card_text`  – формирует текст карточки участника для Telegram.
* `find_photo`             – ищет подходящее фото участника по ФИО.
"""

from __future__ import annotations

import html as std_html
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------------- #
#                     1. Формирование текстовой карточки                      #
# --------------------------------------------------------------------------- #


def build_admin_card_text(card: dict) -> str:
    """
    Собирает человекочитаемый текст для карточки участницы/участника.

    Поля, равные None, "", "null", заменяются на тире.
    Все значения HTML-экранируются, чтобы избежать проблем c форматированием.
    """
    def esc(value: object) -> str:
        return std_html.escape(str(value)) if value not in (None, "", "null") else "—"

    return (
        f"<b>ФИО:</b> {esc(card['full_name'])}\n"
        f"<b>Программа:</b> {esc(card['program'])}\n"
        f"<b>Страна:</b> {esc(card['country'])}\n"
        f"<b>Тик:</b> {esc(card['tik'])}\n"
        f"<b>Статус:</b> {esc(card['status'])}\n"
        f"<b>Возраст:</b> {esc(card['age'])}\n"
        f"<b>Тг:</b> @{esc(card['tg_username']) if card['tg_username'] else '—'}\n"
        f"<b>Подразделение:</b> {esc(card['department'])}\n"
        f"<b>Место работы:</b> {esc(card['workplace'])}\n"
        f"<b>Модуль:</b> {esc(card['module'])}\n"
        f"<b>Должность:</b> {esc(card['position'])}\n"
        f"<b>Руководитель:</b> {esc(card['supervisor_name'])}\n"
        f"<b>HR-балл:</b> {esc(card['hr_feedback'])}\n\n"
        f"<b>Общий рейтинг:</b>\n"
        f"Коэффициент эффективности: {esc(card['efficiency_coefficient'])}\n"
        f"Средний KPI: {esc(card['average_kpi'])} %\n"
        f"Средний Инт.П.: {esc(card['average_int_p'])} %\n"
        f"BCats: {esc(card['bcats'])}\n"
        f"ЗКА: {esc(card['zka'])}\n"
        f"ЗКО: {esc(card['zko'])}\n"
        f"—"
    )


# --------------------------------------------------------------------------- #
#                           2. Поиск фотографии                               #
# --------------------------------------------------------------------------- #

_PHOTOS_DIR: Path = (
    Path(__file__).resolve().parents[1] / "admins" / "superadmin" / "utils" / "photos"
)
_ALLOWED_EXT: set[str] = {".jpg", ".jpeg", ".png", ".webp"}


def _similarity_score(filename: str, target: str) -> float:
    """
    «Похожесть» имени файла на ФИО: 70 % пересечение слов, 30 % fuzzy-ratio.

    Чем выше коэффициент, тем вероятнее, что фото принадлежит нужному
    участнику.  Значения < 0.4 считаем нерелевантными.
    """
    name_parts = {p.lower() for p in filename.split() if len(p) > 1}
    trg_parts = {p.lower() for p in target.split() if len(p) > 1}
    if not trg_parts:
        return 0.0

    word_overlap = len(name_parts & trg_parts) / len(trg_parts)
    fuzz_ratio = SequenceMatcher(None, filename.lower(), target.lower()).ratio()
    return word_overlap * 0.7 + fuzz_ratio * 0.3


def find_photo(full_name: str) -> Optional[Path]:
    """
    Возвращает путь к наиболее подходящему фото по ФИО либо `None`,
    если ничего похожего не найдено или директории нет.
    """
    if not _PHOTOS_DIR.exists():
        return None

    best_score, best_path = 0.0, None
    for fp in _PHOTOS_DIR.iterdir():
        if fp.suffix.lower() not in _ALLOWED_EXT:
            continue

        score = _similarity_score(fp.stem, full_name)
        if score > best_score:
            best_score, best_path = score, fp

    return best_path if best_score >= 0.4 else None
