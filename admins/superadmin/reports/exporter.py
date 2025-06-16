"""
Экспорт отчётов в Excel или PDF + ZIP с изображениями.

Функция верхнего уровня — **export_report()**:
    Path = await export_report(kind, date_from, date_to,
                               fmt="xlsx" | "pdf",
                               abs_places=[...])

* Создаёт DataFrame по SQL-запросу;
* подменяет file_id на миниатюры и собирает картинки;
* пишет Excel (xlsxwriter) или PDF (reportlab);
* упаковывает результат + изображения в ZIP и возвращает путь.

Модуль независим, но использует `config.LOCATION_NAMES` и бот для загрузки фото.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
from PIL import Image
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from config import LOCATION_NAMES, bot
from db.database import conn

# --- директории ------------------------------------------------------------ #
DIR = Path(__file__).resolve().parent
DIR_EXPORT = DIR / "exports"
DIR_IMG = DIR_EXPORT / "images"
DIR_EXPORT.mkdir(parents=True, exist_ok=True)
DIR_IMG.mkdir(exist_ok=True)

pdfmetrics.registerFont(TTFont("DejaVuSans", str(DIR / "fonts" / "DejaVuSans.ttf")))
pdfmetrics.registerFont(
    TTFont("DejaVuSans-Bold", str(DIR / "fonts" / "DejaVuSans-Bold.ttf"))
)

# --- константы ------------------------------------------------------------- #
THUMB = 90     # px
ROW_H = 90     # Excel row height
COL_W = 18     # Excel col width for «Фото»

PHOTO_RE = re.compile(r"(?i)(photo|file|screenshot|argument)")

BOOL_RU = {True: "Да", False: "Нет"}
STATUS_RU = {"approved": "Одобрено", "pending": "На рассмотрении",
             "rejected": "Отклонено", "cancelled": "Отменено"}

RU_HEADERS = {
    "user_name": "Участница",
    "created_at": "Создано",
    "comment": "Комментарий",
    "room_number": "Номер комнаты",
    "cleanliness_status": "Статус чистоты",
    "event_title": "Событие",
    "event_date": "Дата события",
    "attended": "Присутствовала",
    "checked_at": "Проверено",
    "description": "Описание",
    "violation_date": "Дата нарушения",
    "severity": "Серьёзность",
    "reason": "Причина",
    "place": "Локация",
    "date_from": "С",
    "date_to": "По",
    "status": "Статус",
    "photo": "Фото",
    "argument": "Аргумент",
}

# --- SQL-шаблоны (с параметрами d_from / d_to) ----------------------------- #
QUERIES: Dict[str, str] = {
    "clean": """
        SELECT r.id,
               u.full_name  AS user_name,
               r.room_number,
               r.cleanliness_status,
               r.comment,
               r.created_at,
               r.file_id     AS photo
          FROM room_cleanliness_reports r
          JOIN users u ON u.user_id = r.user_id
         WHERE DATE(r.created_at) BETWEEN :d_from AND :d_to
    """,
    "events": """
        SELECT e.title AS event_title,
               e.event_date,
               u.full_name AS user_name,
               ea.attended,
               ea.comment,
               ea.checked_at
          FROM event_attendance ea
          JOIN events e ON e.id = ea.event_id
          JOIN users  u ON u.user_id = ea.user_id
         WHERE DATE(ea.checked_at) BETWEEN :d_from AND :d_to
    """,
    "violations": """
        SELECT v.id,
               u.full_name AS user_name,
               v.description,
               v.violation_date,
               v.severity,
               v.created_at,
               ud.file_path AS argument
          FROM violations v
          JOIN users u ON u.user_id = v.user_id
          LEFT JOIN (
              SELECT user_id, file_path
                FROM user_documents
               WHERE document_type = 'violation_proof'
               GROUP BY user_id
          ) ud ON ud.user_id = v.user_id
         WHERE DATE(v.violation_date) BETWEEN :d_from AND :d_to
    """,
}


# --------------------------------------------------------------------------- #
#                           ВСПОМОГАТЕЛЬНЫЕ                                   #
# --------------------------------------------------------------------------- #
def _iso(d: str) -> str:
    """'31.05.2025' → '2025-05-31' (для SQL)."""
    return datetime.strptime(d, "%d.%m.%Y").strftime("%Y-%m-%d") if "." in d else d


def _fname(kind: str, ext: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DIR_EXPORT / f"{kind}_{ts}_{uuid.uuid4().hex[:6]}.{ext}"


async def _ensure_image(file_id: str) -> Path:
    """Скачивает файл-фото по file_id и кэширует локально."""
    tg = await bot.get_file(file_id)
    dst = DIR_IMG / f"{file_id}{Path(tg.file_path).suffix or '.jpg'}"
    if not dst.exists():
        await bot.download_file(tg.file_path, dst)
    return dst


def _photo_cols(df: pd.DataFrame) -> List[str]:
    """Колонки-фото: file_id, file_path, screenshot …"""
    return [c for c in df.columns if PHOTO_RE.search(c)]


async def _collect_images(df: pd.DataFrame) -> Dict[Tuple[int, str], Path]:
    """
    Находит все изображения, загружает их локально и возвращает маппинг
    (row-idx, col-name) → Path.  Ячейки в DataFrame при этом очищаются.
    """
    out: Dict[Tuple[int, str], Path] = {}
    for r, row in df.iterrows():
        for col in _photo_cols(df):
            val = str(row[col])
            if not val or val == "nan":
                continue
            try:
                p = await _ensure_image(val) if re.fullmatch(r"[\w-]{20,}", val) else Path(val)
            except Exception:
                continue
            out[(r, col)] = p
            df.at[r, col] = ""
    return out


def _strip_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Удаляет колонки 'id' / '*_id', если они есть."""
    return df.drop(columns=[c for c in df.columns if c == "id" or c.endswith("_id")], errors="ignore")


def _translate(df: pd.DataFrame) -> None:
    """Меняет bool/enum значения на русские эквиваленты."""
    if "status" in df.columns:
        df["status"] = df["status"].map(STATUS_RU).fillna(df["status"])
    for col in df.select_dtypes(include=["bool"]).columns:
        df[col] = df[col].map(BOOL_RU)


# --------------------------------------------------------------------------- #
#                             XLSX  /  PDF                                    #
# --------------------------------------------------------------------------- #
def _excel(df: pd.DataFrame, dst: Path, images: Dict[Tuple[int, str], Path]) -> None:
    """Сохраняет DataFrame в Excel + встраивает превью изображений."""
    with pd.ExcelWriter(dst, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Report", startrow=1, header=False)
        wb, ws = writer.book, writer.sheets["Report"]

        header_fmt = wb.add_format({"bold": True, "bg_color": "#eeeeee"})
        for col_idx, col_name in enumerate(df.columns):
            ws.write(0, col_idx, col_name, header_fmt)
            ws.set_column(col_idx, col_idx, COL_W if col_name == "Фото" else 20)

        for (row_idx, col_name), img_path in images.items():
            col_idx = df.columns.get_loc(col_name)
            with Image.open(img_path) as im:
                w, h = im.size
            scale = min(THUMB / w, THUMB / h, 1.0)

            ws.set_row(row_idx + 1, ROW_H)
            ws.insert_image(
                row_idx + 1, col_idx, str(img_path),
                {"x_scale": scale, "y_scale": scale, "url": f"external:images/{img_path.name}",
                 "positioning": 1}
            )


def _pdf(df: pd.DataFrame, dst: Path, images: Dict[Tuple[int, str], Path]) -> None:
    """Пишет PDF-таблицу с изображениями (ReportLab)."""
    c = canvas.Canvas(str(dst), pagesize=landscape(A4))
    page_w, page_h = landscape(A4)

    # — заголовок —
    c.setFont("DejaVuSans-Bold", 14)
    c.drawString(20 * mm, page_h - 15 * mm, f"Отчёт — {dst.stem}")

    col_w = (page_w - 40 * mm) / len(df.columns)
    y = page_h - 25 * mm

    def _new_page():
        nonlocal y
        c.showPage()
        y = page_h - 25 * mm

    # — header —
    c.setFont("DejaVuSans-Bold", 9)
    for i, col in enumerate(df.columns):
        c.drawString(20 * mm + i * col_w, y, str(col))
    c.line(20 * mm, y - 2, page_w - 20 * mm, y - 2)
    c.setFont("DejaVuSans", 8)
    y -= 10 * mm
    row_h = 20 * mm

    for r, row in df.iterrows():
        if y < 20 * mm:
            _new_page()
        for i, (col, val) in enumerate(row.items()):
            x = 20 * mm + i * col_w
            key = (r, col)
            if key in images:
                c.drawImage(str(images[key]), x, y - 5 * mm,
                            width=col_w - 4 * mm, preserveAspectRatio=True, mask="auto")
                c.linkURL(f"external:images/{images[key].name}",
                          (x, y - 5 * mm, x + col_w - 4 * mm, y + row_h - 5 * mm))
            else:
                c.drawString(x, y + 4 * mm, str(val)[:40])
        y -= row_h
    c.save()


# --------------------------------------------------------------------------- #
#                            ОСНОВНАЯ ФУНКЦИЯ                                 #
# --------------------------------------------------------------------------- #
async def export_report(
    kind: str,
    date_from: str,
    date_to: str,
    fmt: str = "xlsx",
    abs_places: Optional[List[str]] | None = None,
) -> Path:
    """Основная точка входа."""
    # — DataFrame —
    params = {"d_from": _iso(date_from), "d_to": _iso(date_to)}
    if kind in QUERIES:
        df = pd.read_sql_query(QUERIES[kind], conn, params=params)
    elif kind == "absence":
        ph = ", ".join("?" * len(abs_places)) if abs_places else ""
        sql = (
            f"""
            SELECT a.id,
                   u.full_name         AS user_name,
                   a.reason,
                   a.place,
                   a.date_from,
                   a.date_to,
                   a.status,
                   af.file_id          AS photo
              FROM absences a
              JOIN users u ON u.user_id = a.user_id
              LEFT JOIN absence_files af ON af.absence_id = a.id
             WHERE DATE(a.date_from) <= :d_to
               AND DATE(a.date_to)   >= :d_from
        """
            + (f" AND a.place IN ({ph})" if ph else "")
        )
        params.update({f"p{i}": v for i, v in enumerate(abs_places or [])})
        df = pd.read_sql_query(sql, conn, params=params)
        df["place"] = df["place"].map(LOCATION_NAMES).fillna(df["place"])
    else:
        raise ValueError(f"Неизвестный тип отчёта: {kind}")

    if df.empty:
        raise ValueError("За выбранный период записей нет.")

    df = _strip_ids(df)
    _translate(df)
    images = await _collect_images(df)
    # переименовать заголовки
    df = df.rename(columns={c: RU_HEADERS.get(c, c) for c in df.columns})
    img_map = {(r, RU_HEADERS.get(c, c)): p for (r, c), p in images.items()}

    # — сохранить —
    if fmt not in {"xlsx", "pdf"}:
        raise ValueError("Формат должен быть xlsx или pdf.")
    file_path = _fname(kind, "pdf" if fmt == "pdf" else "xlsx")
    (_pdf if fmt == "pdf" else _excel)(df, file_path, img_map)

    # — упаковать ZIP с картинками —
    zip_path = _fname(kind, "zip")
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as arc:
        arc.write(file_path, file_path.name)
        for p in set(img_map.values()):
            arc.write(p, Path("images") / p.name)
    file_path.unlink(missing_ok=True)

    # — лог —
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS export_logs(
            id INTEGER PRIMARY KEY,
            report_type TEXT,
            start_date TEXT,
            end_date   TEXT,
            file_path  TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.execute(
        "INSERT INTO export_logs(report_type, start_date, end_date, file_path) VALUES(?,?,?,?)",
        (kind, _iso(date_from), _iso(date_to), str(zip_path)),
    )
    conn.commit()

    return zip_path
