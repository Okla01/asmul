# === file: info.py ===========================================================
import os
from threading import RLock
from typing import Dict, List, Tuple

import pandas as pd

# ------------------ настройки --------------------------
XL_PATH = os.path.join(os.path.dirname(__file__), "excel", "info.xlsx")

# порядок столбцов с переводами вопроса (в файле info.xlsx сначала идут колонки вопросов)
QUESTION_COL2LANG = {0: "ru", 1: "en", 2: "es", 3: "fr", 4: "pt", 5: "ar"}
# порядок столбцов с переводами ответов (ответы идут справа от колонок вопросов)
ANSWER_COL2LANG = {idx + len(QUESTION_COL2LANG): lang for idx, lang in QUESTION_COL2LANG.items()}

PAGE_SIZE = 4  # сколько пунктов в одном «листе» меню

# потокобезопасная «горячая» перезагрузка
_LOCK = RLock()

# глобальная структура для хранения загруженных данных
INFO_DATA: Dict[str, List[Tuple[str, str]]] = {lang: [] for lang in QUESTION_COL2LANG.values()}


def _load() -> Dict[str, List[Tuple[str, str]]]:
    """
    Загружает данные из XLSX и возвращает:
      {lang: [(question_text, answer_text), ...], ...}
    """
    if not os.path.exists(XL_PATH):
        return {lng: [] for lng in QUESTION_COL2LANG.values()}

    df = pd.read_excel(XL_PATH, engine="openpyxl", header=None)
    data: Dict[str, List[Tuple[str, str]]] = {lng: [] for lng in QUESTION_COL2LANG.values()}

    for _, row in df.iterrows():
        # собираем переводы вопроса
        question_texts: Dict[str, str] = {}
        for col_idx, lang in QUESTION_COL2LANG.items():
            if col_idx in row and pd.notna(row[col_idx]):
                question_texts[lang] = str(row[col_idx]).strip()
            else:
                question_texts[lang] = ""

        # собираем переводы ответов
        for col_idx, lang in ANSWER_COL2LANG.items():
            if col_idx not in row or not pd.notna(row[col_idx]):
                continue
            answer_text = str(row[col_idx]).strip()
            if not answer_text:
                continue
            question = question_texts.get(lang, "")
            data[lang].append((question, answer_text))

    return data


def load_info() -> None:
    """
    Полностью пере-инициализировать INFO_DATA, считав данные из XLSX.
    Можно вызывать в любое время работы бота, чтобы обновить FAQ.
    """
    with _LOCK:
        # очищаем текущие данные
        for lang in INFO_DATA:
            INFO_DATA[lang].clear()

        # загружаем свежие данные
        new_data = _load()
        for lang, qa_list in new_data.items():
            INFO_DATA[lang].extend(qa_list)


# первоначальная загрузка при старте модуля
load_info()
