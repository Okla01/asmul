"""
Фоновый планировщик рассылок.

Корутина `mailing_scheduler(bot)` раз в минуту:
1. Берёт из таблицы `mailings` задачи, у которых `scheduled_at` ≤ сейчас.
2. Вызывает `_collect_recipients()` из `handlers.py`, чтобы получить TG-ID.
3. Рассылает сообщения (Markdown) и:
   • для «once» помечает `sent = 1`;
   • для периодических рассчитывает новую дату и сдвигает `scheduled_at`.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from aiogram import Bot, types
from aiogram.enums import ParseMode
from dateutil.relativedelta import relativedelta

from db.database import conn, cursor

CHECK_INTERVAL: int = 60  # секунд между проверками


def _next_run(current: datetime, recurrence: str) -> Optional[datetime]:
    """Вычисляет следующую дату согласно periodic-коду."""
    match recurrence:
        case "daily":
            return current + timedelta(days=1)
        case "weekly":
            return current + timedelta(weeks=1)
        case "monthly":
            return current + relativedelta(months=1)
        case _:
            return None  # 'once' или неизвестное
            

async def mailing_scheduler(bot: Bot) -> None:
    """Корутина-демон; запускать через `asyncio.create_task()` из `main.py`."""
    # локальный импорт, чтобы избежать циклов
    from admins.superadmin.mailing.handlers import _collect_recipients

    while True:
        now_iso = datetime.now().isoformat(timespec="seconds")

        cursor.execute(
            """
            SELECT id, message, filters, recurrence, scheduled_at
              FROM mailings
             WHERE scheduled_at <= ?
               AND (recurrence <> 'once' OR sent = 0)
            """,
            (now_iso,),
        )
        tasks: List[tuple] = cursor.fetchall()

        for mail_id, message, filters_json, recurrence, sched_iso in tasks:
            filters: Dict = json.loads(filters_json or "{}")
            recipients = _collect_recipients(filters)

            for uid in recipients:
                try:
                    await bot.send_message(uid, message, parse_mode=ParseMode.MARKDOWN)
                except Exception:  # pylint: disable=broad-except
                    # можно логировать uid / исключение
                    pass

            next_dt = _next_run(datetime.fromisoformat(sched_iso), recurrence)

            if next_dt is None:  # одноразовая
                cursor.execute("UPDATE mailings SET sent = 1 WHERE id = ?", (mail_id,))
            else:  # периодическая
                cursor.execute(
                    "UPDATE mailings SET scheduled_at = ? WHERE id = ?",
                    (next_dt.isoformat(timespec="seconds"), mail_id),
                )
            conn.commit()

        await asyncio.sleep(CHECK_INTERVAL)
