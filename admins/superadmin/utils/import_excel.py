"""
Модуль `import_excel.py` — вспомогательный скрипт проекта Telegram‑бота: читает Excel‑файл с двумя листами
и синхронизирует данные с таблицей `users` в SQLite‑БД.

Главные задачи:
1. Найти Excel‑файл (`users.xlsx`) в подпапке `excel/` и для каждого листа сделать UPSERT строк в БД.
2. Поддерживать разные структуры блоков внутри листа: данные могут разделяться «шапками» и метками «2024 / 2025».
3. Конвертировать «сырые» значения (телефон, username, ФИО) к единообразному формату.
4. Обеспечивать целостность по «ключевым» полям (`UNIQUE_PRIORITY`), т.е. если пользователь найден по телефону,
   username или ФИО — обновлять, а не дублировать.
5. Поддерживать конкурентный доступ (RLock) для безопасного повторного импорта во время работы бота.
"""

# ────────────────────────────
#           ИМПОРТЫ
# ────────────────────────────
import math             # Для проверки NaN через math.isnan()
import re               # Регулярные выражения для очистки строк
import threading        # RLock → защищаем импорт от параллельного вызова
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd     # Pandas → удобное чтение/обработка Excel

# ───── Подключение к БД (ваш модуль) ──────────────────────────────────────
from db.database import conn, cursor  # conn: sqlite3.Connection, cursor: sqlite3.Cursor

# ──────────────────────────── Константы ────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent        # Папка текущего модуля
EXCEL_PATH = BASE_DIR / "excel" / "users.xlsx"   # Путь к файлу Excel

# Имена листов, которые скрипт ожидает найти
SHEET_SNG = "СВОД СНГ И РФ"
SHEET_MIR = "СВОД МИР"                     # Второе название листа

# Название поля‑столбца в БД, куда кладём «период данных»
DATA_PERIOD_FIELD = "data_period"
TABLE = "users"                             # Целевая таблица в SQLite

# Поля «первого приоритета» при UPSERT — в таком порядке пытаемся найти совпадение
UNIQUE_PRIORITY = ["phone_number", "username", "full_name"]

# Сопоставление «лист Excel → значение поля program»
SHEET_PROGRAM = {
    SHEET_SNG: "СНГ",   # Лист «СВОД СНГ И РФ» → program='СНГ'
    SHEET_MIR: "МИР",   # Лист «СВОД МИР» → program='МИР'
}

# ───── Маппинг «колонка Excel → поле users» ───────────────
#  Одинаков для обоих листов, поэтому вынесен в COMMON_MAPPING
COMMON_MAPPING: Dict[str, str] = {
    "№": None,                              # None → колонка игнорируется
    "ФИО": "full_name",
    "Телефон": "phone_number",
    "Тг": "username",                   # Поддержка рус/лат сокращений
    "TG": "username",
    "Страна": "country",
    "Возраст": "age",
    "Тик": "tik",
    "Статус": "status",
    "Причина исключения": "exclusion_reason",
    "Комментарий": "comment",
    "Объект проживания": "living_space",
    "Дом/кв": "address",
    "Направление АС": "department",
    "Место работы": "workplace",
    "Модуль": "module",
    "Должность": "position",
    "Непосредственный руководитель": "supervisor_name",
    "Итого (Макс 32)": "overall_rating",
    "Коэффициент эффективности": "efficiency_coefficient",
    "BC Solo (Макс 10)": "bcats",
    "ЗКА (Макс 3)": "zka",
    "ЗКО (Макс 3)": "zko",
    "HR‑балл (Макс 3)": "hr_feedback",
    "Дисциплина": "discipline_score",
    "Комментарий (нарушение)": "discipline_comment",
    "Поощрения (Макс 3)": "encouragement_score",
    "Комментарий (активность)": "encouragement_comment",
    "Средний KPI": "average_kpi",
    "СРЕДН. INT-P": "average_int_p",
    "Рейтинг начальника": "supervisor_feedback",
    "Средний балл Рус. яз.": "average_russian_score",
    "Средний РКЛ": "average_raz_kl_score",
    "AS Score": "as_score",
}

# Для каждой книги Excel маппинг одинаков, но структуру оставляем по листам на будущее
COLUMN_MAP = {
    SHEET_SNG: COMMON_MAPPING,
    SHEET_MIR: COMMON_MAPPING,
}

# ──────────────────────────── Утилиты — «нормализация» ────────────────────
SPACE_RE = re.compile(r"\s+")  # Один или более пробелов/табов — убираем


def norm(v: Any) -> str:
    """Приводит строку к «нормализованному» виду:
    - NaN → пустая строка
    - Множественные пробелы/переводы строк → одинарный пробел
    - Регистронезависимо: lower().strip()
    """
    if pd.isna(v):
        return ""
    return SPACE_RE.sub(" ", str(v).replace("\n", " ")).strip().lower()


def clean_phone(v: Any) -> str | None:
    """Оставляем только цифры + убираем всё лишнее. Если ничего не осталось → None."""
    if pd.isna(v):
        return None
    digits = re.sub(r"\D+", "", str(v))
    return digits or None


def clean_username(v: Any) -> str | None:
    """Удаляем лидирующий «@», пробелы. Возвращаем None, если пусто."""
    if pd.isna(v):
        return None
    return str(v).strip().lstrip("@").strip() or None


def is_null(v: Any) -> bool:
    """Унифицированная проверка «значение отсутствует» для строк/чисел/None/NaN."""
    return v is None or (isinstance(v, float) and math.isnan(v)) or v == ""


# ─────────────── Обеспечиваем колонку data_period в users ────────────────

def ensure_data_period_column() -> None:
    """Если в таблице `users` ещё нет столбца `data_period`, добавляем его."""
    cursor.execute("PRAGMA table_info(users)")
    cols = {row[1] for row in cursor.fetchall()}
    if DATA_PERIOD_FIELD not in cols:
        cursor.execute(f"ALTER TABLE users ADD COLUMN {DATA_PERIOD_FIELD} TEXT;")


# ─────────────────── Деление листа на «блоки данных» ─────────────────────
#  Файл Excel может содержать несколько «шапок» — под каждый период (2023/2024 и т.п.).
#  Функции ниже позволяют нарезать лист на DataFrame‑блоки с собственной шапкой.

HEADER_TOKENS = {
    "фио",
    "телефон",
    "тг",
    "tg",
    "возраст",
    "статус",
    "status",
}


def is_header_row(row: pd.Series) -> bool:
    """Определяем «шапку» по наличию ≥2 узнаваемых токенов."""
    return len({norm(c) for c in row.dropna()} & HEADER_TOKENS) >= 2


def iter_blocks(raw_df: pd.DataFrame) -> Iterable[Tuple[pd.DataFrame, str]]:
    """Итерирует лист и отдаёт пары (DataFrame блока, «строка‑метка периода»).

    Алгоритм построчно сканирует DataFrame и:
    • При встрече новой «шапки» закрывает предыдущий буфер и начинает новый.
    • Строка с ≤2 непустыми ячейками трактуется как «метка блока» (год/ап/проч.).
    • Пустая строка завершает блок, если он уже начат.
    """
    header: List[Any] | None = None  # Текущая шапка блока
    buf: List[List[Any]] = []        # Буфер строк текущего блока
    current_label = "current"        # Текущий «период» (по умолчанию)
    pending_label: str | None = None # Лейбл, который вступит в силу после шапки

    for _, row in raw_df.iterrows():
        if is_header_row(row):
            # → Сохраняем предыдущий блок, если он существует
            if header and buf:
                yield pd.DataFrame(buf, columns=header), current_label
                buf.clear()
            # Если до шапки встретилась строка‑метка — применяем
            if pending_label:
                current_label = pending_label
                pending_label = None
            # Обновляем текущую шапку
            header = row.tolist()
            continue

        non_null = row.dropna()

        # Строка‑метка: не шапка и ≤2 непустых ячейки
        if 0 < non_null.count() <= 2 and not is_header_row(row):
            val = norm(non_null.iloc[0])
            if val:
                pending_label = val
            continue

        # «Обычная» строка датасета → добавляем в буфер
        if header:
            if non_null.empty:  # Пустая строка → завершает блок
                if buf:
                    yield pd.DataFrame(buf, columns=header), current_label
                header, buf = None, []
            else:
                buf.append(row.tolist())

    # Финальный блок (если файл не кончался пустой строкой)
    if header and buf:
        yield pd.DataFrame(buf, columns=header), current_label


def translate_label(raw: str) -> str:
    """Приводим строку‑метку к компактному виду: «2024», «2025», «ап», …"""
    r = raw.lower()
    if r.startswith("участ"):
        return "current"
    if "2025" in r:
        return "2025"
    if "2024" in r:
        return "2024"
    if "2023" in r:
        return "2023"
    if r.strip() == "ап":
        return "ап"
    return r[:100] or "current"


# ─────────────────── Фильтры «мусорных» строк внутри блока ────────────────
INVALID_ROW_TOKENS = {"фио", "страна", "country", "full name", "username", "tg"}


def looks_like_header_dup(s: pd.Series) -> bool:
    """Похожа ли строка на повтор шапки внутри блока."""
    return len({norm(v) for v in s.dropna()} & INVALID_ROW_TOKENS) >= 2


def looks_like_year_row(s: pd.Series) -> bool:
    """Проверяем: строка содержит год (4‑значное число) в колонке full_name — такие удаляем."""
    name_val = s.get("full_name")
    return isinstance(name_val, str) and name_val.isdigit() and len(name_val) == 4


# ───────────────────── Подготовка DataFrame блока к UPSERT ────────────────

def prepare_df(
    df: pd.DataFrame,
    mapping: Dict[str, str],
    program_val: str,
    period: str | None = None,
) -> pd.DataFrame:
    """Мэппинг колонок Excel → столбцы БД + очистка/фильтрация строк."""
    if df.empty:
        return pd.DataFrame()

    # 1. Определяем реальные названия колонок в Excel (регистр/пробелы могут различаться)
    real_cols = {norm(c): c for c in df.columns if norm(c)}

    # 2. Строим select‑словарь: Excel‑колонка → поле users
    select = {
        real_cols[norm(src)]: dest
        for src, dest in mapping.items()
        if dest and norm(src) in real_cols
    }
    if not select:
        return pd.DataFrame()  # Нет ни одной нужной колонки

    # 3. Переименовываем/оставляем только нужные столбцы
    df = df[list(select.keys())].rename(columns=select)

    # 4. Очистка телефонов/username
    if "phone_number" in df:
        df["phone_number"] = df["phone_number"].apply(clean_phone)
    if "username" in df:
        df["username"] = df["username"].apply(clean_username)

    # 5. Удаляем «мусорные» строки (дубли шапки, строчка с годом)
    df = df[
        ~df.apply(looks_like_header_dup, axis=1)
        & ~df.apply(looks_like_year_row, axis=1)
    ]

    # 6. Удаляем полностью пустые строки
    df.dropna(how="all", inplace=True)

    # 7. Проставляем program (значение зависит от листа). Россия → отдельное значение «РФ»
    df["program"] = program_val
    if "country" in df.columns:
        mask_russia = (
            df["country"].fillna("").str.strip().str.lower().isin({"россия", "russia"})
        )
        df.loc[mask_russia, "program"] = "РФ"

    # 8. Если передан период — записываем в поле data_period
    if period is not None:
        df[DATA_PERIOD_FIELD] = period

    return df


# ───────────────────────────── UPSERT в БД ───────────────────────────────

def upsert_user(row: Dict[str, Any]) -> None:
    """UPSERT одной записи в таблицу `users` по приоритету из `UNIQUE_PRIORITY`."""
    existing_id = None

    # 1. Пытаемся найти совпадение по телефону / username / ФИО (в указанном порядке)
    for field in UNIQUE_PRIORITY:
        val = row.get(field)
        if val:
            cursor.execute(f"SELECT user_id FROM {TABLE} WHERE {field} = ?", (val,))
            res = cursor.fetchone()
            if res:
                existing_id = res[0]
                break

    # 2. Если пользователь найден → UPDATE только непустых колонок
    if existing_id:
        cols = [k for k, v in row.items() if k != "user_id" and not is_null(v)]
        if not cols:
            return  # Обновлять нечего
        cursor.execute(
            f"UPDATE {TABLE} SET {', '.join(f'{c}=?' for c in cols)} WHERE user_id = ?",
            [row[c] for c in cols] + [existing_id],
        )
    # 3. Если не найден → INSERT новой строки
    else:
        cols = list(row.keys())
        cursor.execute(
            f"INSERT INTO {TABLE} ({', '.join(cols)}) VALUES ({', '.join('?'*len(cols))})",
            [row[c] for c in cols],
        )


# ─────────────────────────── Основная точка входа ─────────────────────────
_import_lock = threading.RLock()  # Гарантируем, что только один импорт идёт одновременно


def import_excel_users(
    xlsx: Path = EXCEL_PATH,
    verbose: bool = True,
) -> None:
    """Главная функция: импортирует пользователей из Excel в БД.

    • Можно вызывать многократно — для «горячего» обновления базы.
    • Использует RLock → не блокирует чтение БД из других потоков.
    • Поддерживает отчётность через флаг `verbose`.
    """
    with _import_lock:
        # 1. Проверяем наличие файла
        if not xlsx.exists():
            raise FileNotFoundError(f"Excel‑файл не найден: {xlsx}")

        # 2. Убеждаемся, что в БД есть колонка data_period
        ensure_data_period_column()

        # 3. Открываем книгу Excel (без чтения всего файла в память)
        book = pd.ExcelFile(xlsx)
        total_rows_imported = 0

        # 4. Проходим по каждому «официальному» листу
        for sheet_name, program_val in SHEET_PROGRAM.items():
            if sheet_name not in book.sheet_names:
                if verbose:
                    print(f"[WARN] Лист '{sheet_name}' отсутствует — пропущен.")
                continue

            raw = book.parse(sheet_name, header=None)  # Читаем лист без авто‑шапок
            rows_this_sheet = 0

            # 5. Нарезаем лист на блоки, каждый блок → prepare_df → UPSERT
            for block_df, raw_label in iter_blocks(raw):
                period = translate_label(raw_label)
                df = prepare_df(block_df, COMMON_MAPPING, program_val, period)
                rows_this_sheet += len(df)
                for _, ser in df.iterrows():
                    upsert_user(ser.dropna().to_dict())

            total_rows_imported += rows_this_sheet
            if verbose:
                print(f"[INFO] {sheet_name}: импортировано {rows_this_sheet} строк (program={program_val})")

        # 6. Сохраняем изменения
        conn.commit()
        if verbose:
            print(f"[OK] Импорт завершён. Всего строк: {total_rows_imported}")
