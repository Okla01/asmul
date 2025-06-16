# utils/locale_to_excel.py
"""
Читает таблицу translations.xlsx и предоставляет функцию reload_translations().
Поддерживает «горячую» подгрузку: если файл изменён, переводы перечитываются.
"""
from pathlib import Path
from typing import Dict
import pandas as pd
import threading

from db.database import load_translations_from_db, replace_all_translations

# ─────────────── НАСТРОЙКИ ────────────────────────────────────────
EXCEL_PATH = Path(__file__).with_name("translations.xlsx")

LANG_COLUMNS = {
    "ru": "Русский",
    "en": "Английский",
    "es": "Испанский",
    "fr": "Французский",
    "pt": "Португальский",
    "ar": "Арабский",
}
# ──────────────────────────────────────────────────────────────────

TRANSLATIONS: Dict[str, Dict[str, str]] = load_translations_from_db()
_last_mtime: float = 0.0
_lock = threading.RLock()  # безопасно для нескольких потоков


def _load_from_db() -> None:
    global TRANSLATIONS, _last_mtime
    TRANSLATIONS.clear()
    TRANSLATIONS.update(load_translations_from_db())
    _last_mtime = EXCEL_PATH.stat().st_mtime


def reload_translations(force: bool = False) -> None:
    """Прочитать файл заново (используйте force=True для ручного перезагрузки)."""
    global TRANSLATIONS, _last_mtime

    with _lock:
        mtime = EXCEL_PATH.stat().st_mtime
        if not force and mtime == _last_mtime:
            return  # файл не менялся

        _load_from_db()
        _last_mtime = mtime


def import_excel_to_db(path: Path = EXCEL_PATH) -> None:
    """Считываем Excel и полностью заменяем таблицу translations."""
    df = pd.read_excel(path, engine="openpyxl")
    if "Ключ" not in df.columns:
        raise ValueError("Нет столбца «Ключ»")
    data = {}
    data = {code: {} for code in LANG_COLUMNS}
    for _, row in df.iterrows():
        key = str(row["Ключ"]).strip()
        if not key or key.lower() == "nan":
            continue
        for code, col in LANG_COLUMNS.items():
            val = row.get(col, "")
            if pd.notna(val) and str(val).strip():
                data[code][key] = str(val).replace("\\n", "\n")

    replace_all_translations(data)  # -> SQLite
    _load_from_db()


def ensure_up_to_date() -> None:
    """
    Проверяет mtime файла и, если он изменился, автоматически перезагружает переводы.
    Вызывается из функции tr() перед доступом к TRANSLATIONS.
    """
    try:
        if EXCEL_PATH.stat().st_mtime != _last_mtime:
            reload_translations()
    except FileNotFoundError:
        # файл пропал – оставляем старые переводы
        pass


# первая загрузка при импорте модуля
# reload_translations(force=True)
