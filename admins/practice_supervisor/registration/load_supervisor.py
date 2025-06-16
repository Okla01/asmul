"""
Bulk-загрузка данных руководителей практики из Excel.

Файл *practice_supervisors.xlsx* (рядом с модулем) содержит колонки:
    user_id | full_name | department | module

При вызове `load_practice_supervisors()` делается UPSERT по full_name.
"""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any, Optional

import pandas as pd

from db.database import conn, cursor

XLSX_PATH: Path = Path(__file__).with_name("practice_supervisors.xlsx")
_LOCK = RLock()


def load_practice_supervisors(path: Optional[Path] = None) -> None:
    """
    Читает Excel и «горячо» обновляет таблицу *practice_supervisors*.

    • если *full_name* уже есть → UPDATE department, module, user_id;  
    • иначе → INSERT новой строки.
    """
    excel = path or XLSX_PATH
    if not excel.exists():
        raise FileNotFoundError(f"Excel-файл не найден: {excel}")

    with _LOCK:
        df = pd.read_excel(excel, engine="openpyxl").iloc[:, :4]
        df.columns = ["user_id", "full_name", "department", "module"]

        for _, row in df.iterrows():
            full_name = str(row["full_name"]).strip()
            if not full_name:
                continue

            department = str(row["department"]).strip()
            module = str(row["module"]).strip()
            raw_uid: Any = row["user_id"]
            uid = None if pd.isna(raw_uid) else int(raw_uid)

            cursor.execute(
                "SELECT id FROM practice_supervisors WHERE full_name = ?;",
                (full_name,),
            )
            existing = cursor.fetchone()

            if existing:
                cursor.execute(
                    """
                    UPDATE practice_supervisors
                       SET department = ?,
                           module     = ?,
                           user_id    = ?
                     WHERE id = ?;
                    """,
                    (department, module, uid, existing["id"]),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO practice_supervisors (full_name, department, module, user_id)
                    VALUES (?, ?, ?, ?);
                    """,
                    (full_name, department, module, uid),
                )
        conn.commit()


# Автоматическая загрузка при импорте (можно отключить)
# load_practice_supervisors()
