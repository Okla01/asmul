import os
import re
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

import pandas as pd
from aiogram.types import FSInputFile

from admins.utils import find_photo

BASE_DIR = Path(__file__).resolve().parent
conn = sqlite3.connect(BASE_DIR / "database.db", check_same_thread=False)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
GROUP_WINDOW_SEC = 5

LANGS = ("ru", "en", "es", "fr", "pt", "ar")
FMT_ISO = "%Y-%m-%d %H:%M:%S"


def set_user_lang(user_id: int, lang: str):
    cursor.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
    conn.commit()


def get_user_lang(user_id: int) -> str:
    cursor.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row and row[0] else "ru"


def get_username(user_id: int) -> str:
    cursor.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row and row[0] else None


def db_user_insert(id: int, username: str, tg_full_name: str):
    cursor.execute('INSERT INTO users (user_id, username, tg_full_name, bot_user) VALUES (?, ?, ?, 1)',
                   (id, username, tg_full_name))
    conn.commit()


def db_user_update(id: int, username: str, tg_full_name: str):
    cursor.execute('UPDATE users SET username = ?, tg_full_name = ?, bot_user = 1 WHERE user_id = ?',
                   (username, tg_full_name, id))
    conn.commit()


def user_exists(user_id: int):
    check = False
    cursor.execute("SELECT EXISTS(SELECT 1 FROM users WHERE user_id = ?)", (user_id,))
    result = cursor.fetchone()
    if result[0] == 1:
        check = True
    return check


def db_user_update_full(
        telegram_id: int,
        full_name: Optional[str] = None,
        gender: Optional[str] = None,
        country: Optional[str] = None,
        phone_number: Optional[str] = None,
        email: Optional[str] = None,
        age: Optional[int] = None
):
    cursor.execute("""
        UPDATE users
        SET full_name = ?,
            gender = ?,
            country = ?,
            phone_number = ?,
            email = ?,
            age = ?
        WHERE user_id = ?
    """, (full_name, gender, country, phone_number, email, age, telegram_id))
    conn.commit()


def add_user_document(
        user_id: int,
        document_type: str,
        file_path: Optional[str] = None,
        reason_of_absence: Optional[str] = None
):
    now = datetime.now()

    # ➊ проверяем, не пора ли «закрыть» старый пакет
    last_ts = _get_last_upload_ts(user_id, document_type)
    same_group = bool(last_ts and now - last_ts <= timedelta(seconds=GROUP_WINDOW_SEC))
    if not same_group:
        # целиком удаляем прежние файлы этого типа
        cursor.execute(
            "DELETE FROM user_documents WHERE user_id=? AND document_type=?",
            (user_id, document_type)
        )

    # ➋ если файл уже есть в текущем пакете — не дублируем
    if file_path:
        exists = cursor.execute(
            "SELECT 1 FROM user_documents "
            "WHERE user_id=? AND document_type=? AND file_path=?",
            (user_id, document_type, file_path)
        ).fetchone()
        if exists:
            return  # тот же file_id уже добавлен

    # ➌ добавляем запись (uploaded_at явно задаём, чтобы в одном пакете
    # была одинаковая метка времени — удобно группировать через SELECT)
    cursor.execute(
        """
        INSERT INTO user_documents
              (user_id, document_type, file_path, reason_of_absence, uploaded_at)
        VALUES (?,      ?,             ?,         ?,                 ?)
        """,
        (user_id, document_type, file_path, reason_of_absence, now.isoformat())
    )
    conn.commit()


def add_simulation_result(user_id: int, simulation_type: str, screenshot_path: str):
    # удаляем предыдущий результат той же симуляции
    cursor.execute(
        "DELETE FROM simulations WHERE user_id=? AND simulation_type=?",
        (user_id, simulation_type)
    )

    cursor.execute(
        """
        INSERT INTO simulations (user_id, simulation_type, screenshot_path, completed_at)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, simulation_type, screenshot_path, datetime.now().isoformat())
    )
    conn.commit()


def get_user_by_employee_number(employee_number: str):
    cursor.execute("""
        SELECT 
            user_id, username, full_name, gender, country, 
            phone_number, email, age, role, employee_number
        FROM users
        WHERE employee_number = ?
    """, (employee_number,))
    row = cursor.fetchone()

    if row is None:
        return None

    # Возвращаем словарь (или кортеж)
    return {
        "user_id": row[0],
        "username": row[1],
        "full_name": row[2],
        "gender": row[3],
        "country": row[4],
        "phone_number": row[5],
        "email": row[6],
        "age": row[7],
        "role": row[8],
        "employee_number": row[9],
    }


def add_faq(question: str, answer: str, for_role: str) -> int:
    cursor.execute(
        "INSERT INTO faq (question, answer, for_role) VALUES (?, ?)",
        (question, answer, for_role)
    )
    conn.commit()
    return cursor.lastrowid


def load_faq_from_db(user_id: int):
    role = get_user_role(user_id)
    cursor.execute("SELECT id, question, answer FROM faq WHERE for_role = ?", (role,))
    rows = cursor.fetchall()
    data = []
    for row in rows:
        data.append({
            "id": row[0],
            "question": row[1],
            "answer": row[2],
        })
    return data


def get_faq_by_id(faq_id: int):
    """
    Возвращает одну запись FAQ по её id, либо пустой словарь, если не найдено.
    """
    cursor.execute("SELECT id, question, answer FROM faq WHERE id = ?", (faq_id,))
    row = cursor.fetchone()
    if row is None:
        return {}
    return {
        "id": row[0],
        "question": row[1],
        "answer": row[2]
    }


def update_faq(faq_id: int, question: str, answer: str) -> bool:
    cursor.execute(
        "UPDATE faq SET question = ?, answer = ? WHERE id = ?",
        (question, answer, faq_id)
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_faq(faq_id: int) -> bool:
    cursor.execute("DELETE FROM faq WHERE id = ?", (faq_id,))
    conn.commit()
    return cursor.rowcount > 0


def _get_last_upload_ts(user_id: int, doc_type: str) -> datetime | None:
    """
    Возвращает uploaded_at последнего файла данного типа или None.
    """
    row = cursor.execute(
        "SELECT uploaded_at FROM user_documents "
        "WHERE user_id=? AND document_type=? "
        "ORDER BY uploaded_at DESC LIMIT 1",
        (user_id, doc_type)
    ).fetchone()
    return datetime.fromisoformat(row[0]) if row else None


def get_user_card_data_by_id(user_id: int = None, tabel_number: str = None) -> Optional[Dict[str, Any]]:
    if tabel_number:
        cursor.execute(
            """
            SELECT  u.user_id                AS id,
                u.full_name,
                u.country,
                u.program,
                u.tik,
                u.status,
                u.age,
                u.username               AS tg_username,
                u.department,
                u.workplace,
                u.module,
                u.position,
                ROUND(u.overall_rating, 2) AS overall_rating,
                ROUND(u.efficiency_coefficient, 2) AS efficiency_coefficient,
                ROUND(u.average_kpi, 2) AS average_kpi,
                u.average_int_p,
                u.bcats,
                ROUND(u.zka, 2) AS zka,
                ROUND(u.zko, 2) AS zko,
                ROUND(u.hr_feedback, 2) AS hr_feedback, 
                u.supervisor_name,
                ud.file_path             -- фото, если храните на диске
        FROM    users u
            LEFT JOIN user_documents ud
                   ON ud.user_id = u.user_id
                  AND ud.document_type = 'photo'     -- convention
            WHERE   u.employee_number = ?
            ORDER BY ud.uploaded_at DESC
            LIMIT 1
            """,
            (tabel_number,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        cols = [c[0] for c in cursor.description]
        return {k: row[i] for i, k in enumerate(cols)}

    else:
        cursor.execute(
            """
            SELECT  u.user_id                AS id,
                    u.full_name,
                    u.country,
                    u.program,
                    u.tik,
                    u.status,
                    u.age,
                    u.username               AS tg_username,
                    u.department,
                    u.workplace,
                    u.module,
                    u.position,
                    ROUND(u.overall_rating, 2),
                    ROUND(u.efficiency_coefficient, 2),
                    ROUND(u.average_kpi, 2),
                    u.average_int_p,
                    u.bcats,
                    ROUND(u.zka, 2),
                    ROUND(u.zko, 2),
                    ROUND(u.hr_feedback, 2),
                    u.supervisor_name,
                    ud.file_path             -- фото, если храните на диске
            FROM    users u
            LEFT JOIN user_documents ud
                   ON ud.user_id = u.user_id
                  AND ud.document_type = 'photo'     -- convention
            WHERE   u.user_id = ?
            ORDER BY ud.uploaded_at DESC
            LIMIT 1
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        cols = [c[0] for c in cursor.description]
        return {k: row[i] for i, k in enumerate(cols)}


def is_stage2_complete(user_id: int) -> bool:
    return has_photo(user_id) and has_passport(user_id) and has_both_sims(user_id)


def has_photo(user_id: int) -> bool:
    return cursor.execute(
        "SELECT 1 FROM user_documents WHERE user_id=? AND document_type='photo' LIMIT 1",
        (user_id,)
    ).fetchone() is not None


def has_passport(user_id: int) -> bool:
    return cursor.execute(
        "SELECT 1 FROM user_documents WHERE user_id=? AND document_type='passport' LIMIT 1",
        (user_id,)
    ).fetchone() is not None


def has_both_sims(user_id: int) -> bool:
    rows = cursor.execute(
        """
        SELECT DISTINCT simulation_type
          FROM simulations
         WHERE user_id=? AND simulation_type IN ('AS_MIR','VS_MIR')
        """,
        (user_id,)
    ).fetchall()
    return {r[0] for r in rows} >= {'AS_MIR', 'VS_MIR'}


def get_user_info_by_id(user_id: int):
    """
    Возвращает кортеж (full_name, username, address, living_space, tg_full_name)
    по user_id из таблицы users.
    (ОСТАВЛЕНА ДЛЯ ОБРАТНОЙ СОВМЕСТИМОСТИ)
    """
    try:
        cursor.execute("""
            SELECT full_name, username, address, living_space, tg_full_name
            FROM users
            WHERE user_id = ?
        """, (user_id,))
        row = cursor.fetchone()
        if row:
            return row
        return None
    except sqlite3.Error as e:
        print(f"Ошибка БД в get_user_info_by_id для user_id {user_id}: {e}")
        return None


def get_participant_card(user_id: int) -> dict | None:
    """
    Возвращает словарь со ВСЕМИ полями, которые нужны на карточке‑админа.
    NULL в БД → None в dict.
    """
    cursor.execute(
        """
        SELECT  u.user_id                AS id,
                u.full_name,
                u.country,
                u.program,
                u.tik,
                u.status,
                u.age,
                u.username               AS tg_username,
                u.department,
                u.workplace,
                u.module,
                u.position,
                ROUND(u.overall_rating, 2) AS overall_rating,
                ROUND(u.efficiency_coefficient, 2) AS efficiency_coefficient,
                ROUND(u.average_kpi, 2) AS average_kpi,
                u.average_int_p,
                u.bcats,
                ROUND(u.zka, 2) AS zka,
                ROUND(u.zko, 2) AS zko,
                ROUND(u.hr_feedback, 2) AS hr_feedback, 
                u.supervisor_name,
                ud.file_path             -- фото, если храните на диске
        FROM    users u
        LEFT JOIN user_documents ud
               ON ud.user_id = u.user_id
              AND ud.document_type = 'photo'     -- convention
        WHERE   u.user_id = ?
        ORDER BY ud.uploaded_at DESC
        LIMIT 1
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    cols = [c[0] for c in cursor.description]
    return {k: row[i] for i, k in enumerate(cols)}


def _get_basic_user(uid: int) -> tuple[str, str | None]:
    """
    Возвращает (full_name, username) по id.
    """
    cursor.execute("SELECT full_name, username FROM users WHERE user_id = ?", (uid,))
    row = cursor.fetchone()
    return (row[0], row[1]) if row else ("—", None)


def _build_card_text_edit_role(uid: int, role_code: str, blocked: bool) -> str:
    """
    Формирует текст карточки с актуальными данными.
    """
    full_name, username = _get_basic_user(uid)
    username_part = f" (@{username})" if username else ""
    status_part = "🚫 Заблокирован" if blocked else "✅ Активен"
    from config import ROLES
    return (
        f"👤 <b>{full_name}</b>{username_part}\n"
        f"ID: <code>{uid}</code>\n"
        f"Текущая роль: <b>{ROLES[role_code]}</b>\n"
        f"Статус: {status_part}\n\n"
        f"Выберите действие:"
    )


def _casefold(s):
    """Unicode-безрегистр: str.casefold() безопасен для всех языков."""
    return s.casefold() if s is not None else None


# Функция CF() теперь доступна в SQL
conn.create_function("CF", 1, _casefold)


def _normalize_fio(query: str) -> str:
    """
    Упрощённая нормализация: убираем двойные пробелы
    и превращаем 'Иванов Иван' → '%иванов%иван%'.
    Уже в casefold-регистре.
    """
    query = re.sub(r"\s+", " ", query.strip())
    return "%" + "%".join(query.split(" ")) + "%"


def search_users_by_fio(
        query: str,
        limit: int = 25,
        is_bot_user: bool = True,
        ps_user_id: int | None = None
) -> List[Dict[str, Any]]:
    q_cf = query.casefold()
    fio_pattern = _normalize_fio(q_cf)  # '%иванов%иван%'
    username_pattern = f"%{q_cf.lstrip('@')}%"  # '%ivanov%'

    from config import ROLES
    role_codes = [
        code for code, title in ROLES.items()
        if q_cf in title.casefold() or q_cf in code.casefold()
    ]
    role_placeholders = ", ".join("?" * len(role_codes)) if role_codes else ""
    bot_user_filter = "AND bot_user = 1" if is_bot_user else ""

    # Если передан ps_user_id, пытаемся получить у него department и module
    if ps_user_id is not None:
        cursor.execute(
            "SELECT department, module FROM practice_supervisors WHERE user_id = ?",
            (ps_user_id,)
        )
        ps_row = cursor.fetchone()
        if not ps_row:
            return []  # РП не найден – сразу пусто

        ps_department = ps_row["department"]
        ps_module = ps_row["module"]

        sql = f"""
            SELECT user_id AS id, full_name, COALESCE(tik, 0) AS tik
            FROM   users
            WHERE  (
                     CF(full_name) LIKE ?
                  OR CF(username)   LIKE ?
                  {"OR role IN (" + role_placeholders + ")" if role_codes else ""}
                  )
              {bot_user_filter}
              AND department = ?
              AND module     = ?
            ORDER  BY full_name
            LIMIT  ?
        """
        params: list[Any] = [fio_pattern, username_pattern]
        if role_codes:
            params += role_codes
        params += [ps_department, ps_module, limit]

        cursor.execute(sql, params)
        cols = [c[0] for c in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    # Без ps_user_id – обычное поведение без фильтра department/module
    sql = f"""
        SELECT user_id AS id, full_name, COALESCE(tik, 0) AS tik
        FROM   users
        WHERE  (
                 CF(full_name) LIKE ?
              OR CF(username)   LIKE ?
              {"OR role IN (" + role_placeholders + ")" if role_codes else ""} {bot_user_filter}
              )
        ORDER  BY full_name
        LIMIT  ?
    """
    params: list[Any] = [fio_pattern, username_pattern]
    if role_codes:
        params += role_codes
    params += [limit]

    cursor.execute(sql, params)
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def get_photo_or_none(card: dict) -> FSInputFile | str | None:
    """
    • если в БД уже сохранён file_id – возвращаем его;
    • иначе ищем файл по ФИО и отдаём FSInputFile;
    • если не найдено – None.
    """
    file_id = card.get("photo_id")
    if file_id:
        return file_id

    path = find_photo(card["full_name"])
    return FSInputFile(path) if path else None


def add_cleanliness_report(user_id: int, room_number: str):
    """
    Создаёт запись в room_cleanliness_reports со статусом «ожидает_оценки».
    Возвращает ID созданной записи.
    """
    cursor.execute("""
        INSERT INTO room_cleanliness_reports (user_id, cleanliness_status, room_number)
        VALUES (?, 'ожидает_оценки', ?)
    """, (user_id, room_number))
    conn.commit()
    return cursor.lastrowid


def update_cleanliness_report(report_id: int, new_status: str, comment: str):
    """
    Обновляет запись в room_cleanliness_reports, задавая cleanliness_status и comment.
    """
    cursor.execute("""
        UPDATE room_cleanliness_reports
        SET cleanliness_status = ?, comment = ?
        WHERE id = ?
    """, (new_status, comment, report_id))
    conn.commit()


def get_user_id_by_report_id(report_id: int) -> int:
    """
    Возвращает user_id, связанный с записью в room_cleanliness_reports.
    Если не найдено, вернёт 0.
    """
    cursor.execute("SELECT user_id FROM room_cleanliness_reports WHERE id = ?", (report_id,))
    row = cursor.fetchone()
    if row:
        return row[0]
    return 0


def get_event_by_id(ev_id: int) -> dict | None:
    purge_expired_events()
    cursor.execute("SELECT * FROM events WHERE id=?", (ev_id,))
    row = cursor.fetchone()
    if not row:
        return None
    cols = [c[0] for c in cursor.description]
    return dict(zip(cols, row))


def create_event(title: str, description: str, event_date: str) -> int:
    """
    Создаём новое мероприятие и возвращаем его ID.
    event_date может быть строкой в ISO-формате или timestamp.
    """
    now = datetime.now().isoformat()
    cursor.execute(
        "INSERT INTO events (title, description, event_date, created_at) "
        "VALUES (?, ?, ?, ?)",
        (title, description, event_date, now)
    )
    conn.commit()
    return cursor.lastrowid


def purge_expired_events() -> None:
    """
    Находит активные события с просроченным дедлайном
    и переводит их в status='deleted'.
    """
    now = datetime.now().strftime(FMT_ISO)
    cursor.execute("""
        UPDATE events
           SET status = 'deleted'
         WHERE status = 'active'
           AND report_deadline IS NOT NULL
           AND report_deadline < ?
    """, (now,))
    conn.commit()


def mark_user_attendance(event_id: int, user_id: int, attended: bool, comment: str, photo_id: str):
    """
    Создаём или обновляем запись в event_attendance для user_id и event_id.
    'attended' (True/False) — был ли пользователь на мероприятии.
    'comment' может содержать отчёт, ссылку на фото и т. д.
    """
    now = datetime.now().isoformat()

    # Проверяем, есть ли уже запись
    cursor.execute(
        "SELECT id FROM event_attendance WHERE event_id=? AND user_id=?",
        (event_id, user_id)
    )
    row = cursor.fetchone()

    if row:
        attendance_id = row[0]
        cursor.execute(
            "UPDATE event_attendance "
            "SET attended=?, comment=?, checked_at=?, photo_id=?"
            "WHERE id=?",
            (1 if attended else 0, comment, now, photo_id, attendance_id)
        )
    else:
        cursor.execute(
            "INSERT INTO event_attendance (event_id, user_id, attended, comment, checked_at, photo_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, user_id, 1 if attended else 0, comment, now, photo_id)
        )
    conn.commit()


def get_attendance_info(event_id: int, user_id: int) -> dict:
    """
    Получаем одну запись из event_attendance (или пустой словарь).
    """
    cursor.execute(
        "SELECT id, event_id, user_id, attended, comment, checked_at, photo_id "
        "FROM event_attendance "
        "WHERE event_id=? AND user_id=?",
        (event_id, user_id)
    )
    row = cursor.fetchone()
    if not row:
        return {}
    return {
        "id": row[0],
        "event_id": row[1],
        "user_id": row[2],
        "attended": bool(row[3]),
        "comment": row[4],
        "checked_at": row[5],
        "photo_id": row[6]
    }


def get_all_events(status: str = "active") -> list[dict]:
    purge_expired_events()  # ← авто-архивация
    cursor.execute("SELECT * FROM events WHERE status=? ORDER BY event_date", (status,))
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def admin_update_attendance(attendance_id: int, approved: bool):
    """
    Админ подтверждает или отклоняет отчёт.
    - approved=True => attended=1
    - approved=False => attended=0
    Также обновляем поле checked_at текущим временем.
    """
    now = datetime.now().isoformat()
    attended_val = 1 if approved else 0

    cursor.execute("""
        UPDATE event_attendance
           SET attended = ?,
               checked_at = ?
         WHERE id = ?
    """, (attended_val, now, attendance_id))
    conn.commit()


def get_attendance_by_id(attendance_id: int) -> dict:
    """
    Возвращает запись из event_attendance вместе с данными о мероприятии (JOIN с events).
    Пример результата:
    {
      "id": 12,
      "event_id": 3,
      "user_id": 123456,
      "attended": True,
      "comment": "photo_file_id=...",
      "checked_at": "2025-08-20T15:34:12",
      "photo_id": "...",
      "event_title": "Ефрейторство ФИНАЛ",
      "event_date": "2024-08-21 20:00:00"
    }
    Если запись не найдена, вернётся пустой словарь {}.
    """
    cursor.execute("""
        SELECT ea.id,
               ea.event_id,
               ea.user_id,
               ea.attended,
               ea.comment,
               ea.checked_at,
               ea.photo_id,
               e.title,
               e.event_date
          FROM event_attendance ea
          JOIN events e ON e.id = ea.event_id
         WHERE ea.id = ?
    """, (attendance_id,))
    row = cursor.fetchone()
    if not row:
        return {}

    return {
        "id": row[0],
        "event_id": row[1],
        "user_id": row[2],
        "attended": bool(row[3]),
        "comment": row[4],
        "checked_at": row[5],
        "photo_id": row[6],
        "event_title": row[7],
        "event_date": row[8]
    }


# 🔄 1.  Новый helper: одна запись = одно место
def _insert_absence(user_id: int,
                    reason: str,
                    place: str,
                    date_from: str,
                    date_to: str,
                    files: list[tuple]) -> int:
    cur = conn.execute(
        """INSERT INTO absences
              (user_id, reason, place, date_from, date_to, status)
           VALUES (?, ?, ?, ?, ?, 'pending')""",
        (user_id, reason, place, date_from, date_to),
    )
    absence_id = cur.lastrowid

    # те же файлы привязываем к каждой записи (если надо – не меняйте)
    for ftype, file_id, filename in files:
        conn.execute(
            "INSERT INTO absence_files (absence_id, file_id, filename) "
            "VALUES (?, ?, ?)",
            (absence_id, file_id, filename),
        )
    return absence_id


def get_user_id_by_attendance_id(attendance_id: int) -> int | None:
    cursor.execute(
        "SELECT user_id FROM event_attendance WHERE id = ?",
        (attendance_id,)
    )
    row = cursor.fetchone()
    if row:
        return row[0]  # Возвращаем user_id
    else:
        return None  # Запись с таким attendance_id не найдена


def add_absence_records_to_db(user_id: int, data: dict) -> list[int]:
    """Создаёт по одной записи на каждое место, возвращает список id."""
    reason_txt = {
        "illness": "Болезнь",
        "family": "Семейные обстоятельства",
        "vacation": "Отпуск",
        "other": f"Другое: {data.get('other_text', '') or '—'}",
    }.get(data.get("reason_code"), "—")

    date_from, date_to = data["dates"]["start"], data["dates"]["end"]
    files = data.get("files", [])
    locations = data.get("locations") or ["—"]

    ids = []
    for place in locations:
        ids.append(
            _insert_absence(user_id, reason_txt, place, date_from, date_to, files)
        )
    conn.commit()
    return ids


def add_absence_record_to_db(user_id: int, data: dict) -> int:
    ids = add_absence_records_to_db(user_id, data)
    return ids[0] if ids else 0


def _set_absence_status(absence_id: int, admin_id: int,
                        status: str, comment: str = "") -> None:
    conn.execute(
        """UPDATE absences
              SET status = ?, admin_id = ?, decision_comment = ?, decided_at = ?
            WHERE id = ?""",
        (status, admin_id, comment, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), absence_id),
    )
    conn.commit()


def approve_absence(absence_id: int, admin_id: int, comment: str = "") -> None:
    _set_absence_status(absence_id, admin_id, "approved", comment)


def reject_absence(absence_id: int, admin_id: int, comment: str) -> None:
    _set_absence_status(absence_id, admin_id, "rejected", comment)


def get_user_by_absence(absence_id: int) -> int:
    row = conn.execute("SELECT user_id FROM absences WHERE id = ?", (absence_id,)).fetchone()

    return row[0] if row else 0


def get_absence_info(absence_id: int) -> dict:
    row = conn.execute(
        """SELECT id, user_id, reason, place, date_from, date_to, status
             FROM absences
            WHERE id = ?""",
        (absence_id,)
    ).fetchone()
    if not row:
        return {}
    return dict(row)


def add_absences_for_locations(user_id: int, data: dict) -> dict[str, int]:
    """
    Создаёт по одной записи в absences на каждую локацию.
    Возвращает словарь {location: absence_id}.
    """
    ids: dict[str, int] = {}
    for loc in data["locations"]:
        rec_data = data.copy()
        rec_data["locations"] = [loc]  # ← только одна локация
        ids[loc] = add_absence_record_to_db(user_id, rec_data)  # уже существующая функция
    return ids


def get_user_role(user_id: int) -> str | None:
    cursor.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row and row[0] else None


def get_tabel_number_by_user_id(user_id: int) -> str:
    cursor.execute("SELECT employee_number FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()[0]
    return row if row else None


def set_user_role(user_id: int, role: str) -> None:
    cursor.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))
    conn.commit()


def get_employee_by_tabel_number(tabel: str):
    """
    Возвращает dict с полями id, full_name, employee_number
    либо None, если сотрудник не найден.
    """
    cursor.execute(
        """
        SELECT user_id   AS id,
               full_name,
               employee_number
        FROM   users
        WHERE  employee_number = ?
        """,
        (tabel,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    # корректное преобразование Row → dict
    return row


def block_user(user_id: int, reason: str = "auto_registration_fail") -> None:
    cursor.execute(
        """
        UPDATE users
           SET status           = 'blocked',
               exclusion_reason = COALESCE(exclusion_reason, ?)
         WHERE user_id          = ?
        """,
        (reason, user_id),
    )
    conn.commit()


def unblock_user(user_id: int) -> None:
    cursor.execute(
        """
        UPDATE users
           SET status           = NULL,
               exclusion_reason = NULL
         WHERE user_id          = ?
        """,
        (user_id,),
    )
    conn.commit()


def save_practice_feedback(data: dict):
    """data = {user_id, supervisor_id, tik, year, quarter, zka, zko, absence}"""
    conn.execute("""
        INSERT INTO practice_feedback
          (user_id, supervisor_id, tik, year, quarter, zka, zko, absence)
          VALUES (:user_id, :sup, :tik, :year, :q, :zka, :zko, :abs)
    """, {"user_id": data["user_id"], "sup": data["sup_id"], "tik": data["tik"],
          "year": data["year"], "q": data["quarter"], "zka": data["zka"],
          "zko": data["zko"], "abs": data["absence"]})
    conn.commit()


def feedback_exists(uid: int, tik: int, year: int, q: int) -> bool:
    row = conn.execute("""SELECT 1 FROM practice_feedback
                          WHERE user_id=? AND tik=? AND year=? AND quarter=?""",
                       (uid, tik, year, q)).fetchone()
    return bool(row)


def _slugify(text: str, max_len: int = 40) -> str:
    """
    Упрощённая транслитерация для имён папок/файлов.
    Пример:  «Иванова Ольга» -> ivanova_olga
    """
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)  # убрали символы
    text = re.sub(r"[-\s]+", "_", text).strip("_")
    return text[:max_len] or "user"


async def _download_telegram_file(bot, file_id: str, dest_base: Path):
    """
    Качает файл по file_id и сохраняет на диске.
    Если не удалось — создаёт .txt-заглушку.
    """
    try:
        tg_file = await bot.get_file(file_id)  # ①
        suffix = Path(tg_file.file_path).suffix or ".bin"
        dest = dest_base.with_suffix(suffix)
        await bot.download(tg_file, destination=dest)  # ②
    except Exception as e:
        with open(dest_base.with_suffix(".txt"), "w", encoding="utf-8") as f:
            f.write(f"Не удалось скачать {file_id}\n{e}")


async def export_candidates_zip_async(bot, role_code: str = "user_unauthorized") -> str:
    """
    Асинхронно формирует excel + все документы/скрины,
    скачивая file_id из Telegram, затем архивирует в .zip.

    Возвращает абсолютный путь к архиву.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    root_dir = Path("exports") / f"candidates_{ts}"
    docs_dir = root_dir / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)

    # 1. все кандидаты
    cursor.execute(
        """
        SELECT user_id, username, full_name, tg_full_name, gender, country,
               phone_number, email, age, program
        FROM   users
        WHERE  role LIKE ?
        """,
        (f"{role_code}%",)
    )
    candidates = cursor.fetchall()

    # 2. excel
    pd.DataFrame([dict(r) for r in candidates]).to_excel(root_dir / "candidates.xlsx", index=False)

    # 3. собираем документы
    for row in candidates:
        uid = row["user_id"]
        name_for_slug = row["full_name"] or row["tg_full_name"] or row["username"] or str(uid)
        sub = docs_dir / f"{uid}_{_slugify(name_for_slug)}"
        sub.mkdir(exist_ok=True)

        # 3.1 документы
        cursor.execute(
            """SELECT document_type, file_path, reason_of_absence
               FROM user_documents WHERE user_id=?""", (uid,)
        )
        docs = cursor.fetchall()
        for idx, doc in enumerate(docs, 1):
            src = doc["file_path"]
            dst_base = sub / f"{doc['document_type']}_{idx}"
            if src and os.path.isfile(src):  # локальный файл
                shutil.copy2(src, dst_base.with_suffix(Path(src).suffix))
            elif src:  # file_id
                await _download_telegram_file(bot, src, dst_base.with_suffix(".bin"))
            else:  # нет файла → причина
                with open(dst_base.with_suffix(".txt"), "w", encoding="utf-8") as f:
                    f.write(doc["reason_of_absence"] or "—")

        # 3.2 скрины симуляций
        cursor.execute("SELECT simulation_type, screenshot_path FROM simulations WHERE user_id=?", (uid,))
        sims = cursor.fetchall()
        for sim in sims:
            src = sim["screenshot_path"]
            dst = sub / f"{sim['simulation_type']}"
            if src and os.path.isfile(src):
                shutil.copy2(src, dst.with_suffix(Path(src).suffix))
            elif src:  # file_id
                await _download_telegram_file(bot, src, dst.with_suffix(".bin"))

    # 4. архив
    zip_path = shutil.make_archive(str(root_dir), "zip", root_dir)

    # 5. лог
    cursor.execute("INSERT INTO export_logs (report_type, file_path) VALUES ('candidates_export', ?)", (zip_path,))
    conn.commit()

    return zip_path


def load_translations_from_db() -> dict[str, dict[str, str]]:
    """Читаем всю таблицу -> {lang: {key: txt, …}, …}"""
    rows = cursor.execute("SELECT * FROM translations").fetchall()
    data = {l: {} for l in LANGS}
    for row in rows:
        k = row["key_text"]
        for l in LANGS:
            if row[l]:
                data[l][k] = row[l]
    return data


def replace_all_translations(data: dict[str, dict[str, str]]):
    """Полностью перезаписываем таблицу translations."""
    cursor.execute("DELETE FROM translations")
    conn.commit()
    # --- 1. вставляем уникальные key_text ---------------------------------
    all_keys = {k for pairs in data.values() for k in pairs.keys()}
    cursor.executemany(
        "INSERT INTO translations (key_text) VALUES (?) "
        "ON CONFLICT(key_text) DO NOTHING",
        [(k,) for k in all_keys]
    )

    # --- 2. обновляем значения по языкам -----------------------------------
    for lang, pairs in data.items():
        for key, txt in pairs.items():
            cursor.execute(
                f"UPDATE translations SET {lang} = ? WHERE key_text = ?",
                (txt, key)
            )

    conn.commit()


def _is_blocked(uid: int) -> bool:
    cursor.execute("SELECT status FROM users WHERE user_id = ?", (uid,))
    row = cursor.fetchone()
    return bool(row and row[0] == "blocked")


def is_notifed(uid: int) -> bool:
    cursor.execute("SELECT notifed_send FROM users WHERE user_id = ?", (uid,))
    row = cursor.fetchone()
    return row[0]


def set_notifed(uid: int, notifed: bool):
    cursor.execute("UPDATE users SET notifed_send = ? WHERE user_id = ?", (notifed, uid))
    conn.commit()


def get_bool_setting(key: str, default: bool = False) -> bool:
    cursor.execute("SELECT value FROM settings WHERE key_setting = ?", (key,))
    row = cursor.fetchone()
    if row is None:
        return default
    return row[0] == "1"


def set_bool_setting(key: str, val: bool) -> None:
    cursor.execute(
        "INSERT INTO settings(key_setting, value) VALUES(?, ?) "
        "ON CONFLICT(key_setting) DO UPDATE SET value = excluded.value",
        (key, "1" if val else "0")
    )
    conn.commit()


def get_reg_translation(key: str) -> str:
    """
    Возвращает текст по ключу из таблицы reg_translations.
    Если ключ не найден — возвращает сам key.
    """
    row = cursor.execute(
        "SELECT text FROM reg_translations WHERE key_text = ?", (key,)
    ).fetchone()
    return row["text"] if row else key


def find_ps_by_full_name(full_name: str) -> sqlite3.Row | None:
    cursor.execute("SELECT * FROM practice_supervisors WHERE full_name = ?", (full_name,))
    return cursor.fetchone()


def update_ps_user_id(ps_id: int, user_id: int) -> None:
    cursor.execute("UPDATE practice_supervisors SET user_id = ? WHERE id = ?", (user_id, ps_id))
    conn.commit()


def insert_practice_supervisor(full_name: str, department: str, module: str, user_id: int) -> int:
    cursor.execute(
        "INSERT INTO practice_supervisors (full_name, department, module, user_id) VALUES (?, ?, ?, ?)",
        (full_name, department, module, user_id)
    )
    conn.commit()
    return cursor.lastrowid


def create_ps_request(
        user_id: int,
        full_name: str,
        department: str,
        module: str | None,
        is_existing: bool,
        ps_id: int | None = None
) -> int:
    cursor.execute(
        """
        INSERT INTO ps_requests (user_id, full_name, department, module, is_existing, ps_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, full_name, department, module, int(is_existing), ps_id)
    )
    conn.commit()
    return cursor.lastrowid


def get_ps_request_by_id(req_id: int) -> sqlite3.Row | None:
    cursor.execute("SELECT * FROM ps_requests WHERE id = ?", (req_id,))
    return cursor.fetchone()


def update_ps_request_status(req_id: int, status: str) -> None:
    cursor.execute("UPDATE ps_requests SET status = ? WHERE id = ?", (status, req_id))
    conn.commit()


def delete_ps_request(req_id: int) -> None:
    """
    Удаляет запись-запрос из ps_requests (например, после обработки).
    """
    cursor.execute("DELETE FROM ps_requests WHERE id = ?", (req_id,))
    conn.commit()


def has_pending_ps_request(user_id: int) -> bool:
    """
    Проверяет, есть ли у пользователя с given user_id незавершённая (status='pending') запись в ps_requests.
    Возвращает True, если такая запись существует, иначе False.
    """
    cursor.execute(
        "SELECT 1 FROM ps_requests WHERE user_id = ? AND status = 'pending' LIMIT 1",
        (user_id,)
    )
    return cursor.fetchone() is not None


def get_all_departments() -> List[str]:
    """
    Возвращает отсортированный список уникальных department из таблицы users (не NULL, не пустые).
    """
    cursor.execute(
        "SELECT DISTINCT department FROM users WHERE department IS NOT NULL AND TRIM(department) != '' ORDER BY department")
    rows = cursor.fetchall()
    return [row["department"] for row in rows]


def get_modules_by_department(department: str) -> List[str]:
    """
    Возвращает отсортированный список уникальных module из таблицы users,
    где department = переданному (точное совпадение, нечувствительное к регистру).
    """
    cursor.execute(
        "SELECT DISTINCT module FROM users WHERE CF(department) = CF(?) AND module IS NOT NULL AND TRIM(module) != '' ORDER BY module",
        (department,)
    )
    rows = cursor.fetchall()
    return [row["module"] for row in rows]


def create_admin_registration_table():
    """Создаёт таблицу для заявок на регистрацию администраторов."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            target_role TEXT NOT NULL,
            fio TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_by INTEGER,
            approved_at TIMESTAMP,
            comment TEXT
        )
    """)
    conn.commit()

    # Создаём индекс для быстрого поиска по user_id
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_admin_reg_user_id
        ON admin_registrations (user_id)
    """)
    conn.commit()


def add_admin_registration(user_id: int, target_role: str, fio: str) -> int:
    """Добавляет новую заявку на регистрацию."""
    cursor.execute("""
        INSERT INTO admin_registrations (user_id, target_role, fio)
        VALUES (?, ?, ?)
    """, (user_id, target_role, fio))
    conn.commit()
    return cursor.lastrowid


def get_user_registrations(user_id: int) -> list[dict]:
    """Возвращает список заявок пользователя на регистрацию."""
    cursor.execute("""
        SELECT id, target_role, fio, status, created_at, 
               approved_by, approved_at, comment
        FROM admin_registrations
        WHERE user_id = ?
        ORDER BY created_at DESC
    """, (user_id,))
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def update_registration_status(reg_id: int, status: str, approved_by: int = None, comment: str = None) -> None:
    """Обновляет статус заявки на регистрацию."""
    cursor.execute("""
        UPDATE admin_registrations
        SET status = ?, approved_by = ?, approved_at = CURRENT_TIMESTAMP, comment = ?
        WHERE id = ?
    """, (status, approved_by, comment, reg_id))
    conn.commit()
