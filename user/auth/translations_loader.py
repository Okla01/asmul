# === file: db/translations_loader.py ==========================================

import sqlite3
import pandas as pd
from pathlib import Path
from threading import RLock

from db.database import cursor, conn

# ─── Настройки ───────────────────────────────────────────────────────────────
# Путь к Excel-файлу (texts_part.xlsx).
# Предполагается, что файл лежит рядом с этим модулем.
XLSX_PATH = Path(__file__).parent.parent / "auth" / "texts_part.xlsx"

# Имя таблицы в SQLite
TABLE_NAME = "reg_translations"

# Блокировка для потокобезопасности «горячей» перезагрузки
_LOCK = RLock()


# ─── Основная функция «горячей» загрузки ──────────────────────────────────────
def load_reg_translations():
    """
    Считывает Excel-файл с переводами и «гарячо» обновляет таблицу reg_translations.
    Если ключа нет в таблице — вставляет новую запись.
    Если ключ найден — обновляет текст.
    """
    from db.database import cursor, conn
    with _LOCK:
        # 1. Проверяем наличие Excel-файла
        if not XLSX_PATH.exists():
            raise FileNotFoundError(f"Excel-файл не найден: {XLSX_PATH}")

        # 2. Читаем весь лист в DataFrame
        df = pd.read_excel(XLSX_PATH, engine="openpyxl")
        df = df.iloc[:, :2]
        df.columns = ["key_text", "text"]

        # 4. Проверяем, что таблица reg_translations существует. Если нет — создаём её.
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                key_text   TEXT PRIMARY KEY,
                text       TEXT NOT NULL
            );
        """)
        conn.commit()

        # 5. Для каждой строки делаем UPSERT
        for _, row in df.iterrows():
            key = str(row["key_text"]).strip()
            txt = str(row["text"]).strip()

            if not key:
                # Пропускаем пустые ключи
                continue

            # пытаемся обновить: если запись есть, UPDATE, иначе INSERT
            cursor.execute(
                f"SELECT 1 FROM {TABLE_NAME} WHERE key_text = ?;",
                (key,)
            )
            exists = cursor.fetchone() is not None

            if exists:
                cursor.execute(
                    f"UPDATE {TABLE_NAME} SET text = ? WHERE key_text = ?;",
                    (txt, key)
                )
            else:
                cursor.execute(
                    f"INSERT INTO {TABLE_NAME} (key_text, text) VALUES (?, ?);",
                    (key, txt)
                )

        # 6. Фиксируем изменения и закрываем соединение
        conn.commit()

load_reg_translations()
