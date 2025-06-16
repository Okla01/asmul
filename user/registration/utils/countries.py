# === file: countries.py ======================================================
import re
from pathlib import Path
from threading import RLock
from typing import Dict, List, Set

import pandas as pd

XL_PATH = Path(__file__).with_name("excel").joinpath("countries.xlsx")
PAGE_SIZE_COUNTRY = 8
LANGS = ["ru", "en", "es", "fr", "pt", "ar"]
N_CIS = 7

COUNTRY_LIST: Dict[str, List[str]] = {}
CIS_SET: Dict[str, Set[str]] = {lang: set() for lang in LANGS}

PHONE_CODE: Dict[str, str] = {}   # "Russia" → "+7"
PHONE_MASK: Dict[str, str] = {}   # "Russia" → "___ ___-__-__"
CODE_MASK: Dict[str, str] = {}    # "+7"     → "___ ___-__-__"

# потокобезопасная «горячая» перезагрузка
_LOCK = RLock()


def load_countries() -> None:
    """
    Считать Excel и ПОЛНОСТЬЮ пере-инициализировать все словари даже во время
    работы бота. Можно вызывать сколько угодно раз — данные всегда актуальны.
    """
    with _LOCK:
        if not XL_PATH.exists():
            raise FileNotFoundError(f"{XL_PATH} not found")

        # ─ 1. очищаем все кэш-структуры ─────────────────────────────
        COUNTRY_LIST.clear()
        for lang in LANGS:
            COUNTRY_LIST[lang] = []

        for lang in LANGS:
            CIS_SET[lang].clear()

        PHONE_CODE.clear()
        PHONE_MASK.clear()
        CODE_MASK.clear()

        # ─ 2. читаем файл ───────────────────────────────────────────
        df = pd.read_excel(XL_PATH, header=None, engine="openpyxl")

        # --- названия стран ----------------------------------------
        for col, lang in enumerate(LANGS):
            col_data = df.iloc[:, col].fillna("").astype(str).str.strip()
            COUNTRY_LIST[lang] = col_data.tolist()
            CIS_SET[lang] = set(col_data.head(N_CIS))

        # --- коды телефонов / маски --------------------------------
        codes = df.iloc[:, 6].astype(str).str.strip().str.lstrip("+")
        raw_masks = df.iloc[:, 7].astype(str).str.strip()

        for i, (code, mask_raw) in enumerate(zip(codes, raw_masks)):
            if not code.isdigit():
                continue  # пропускаем строки без кода

            code = f"+{code}"
            mask = re.sub(r"[+#0-9]", "_", mask_raw) or "__________"

            CODE_MASK[code] = mask
            for lang, names in COUNTRY_LIST.items():
                name = names[i].strip()
                if name:
                    PHONE_CODE[name] = code
                    PHONE_MASK[name] = mask


# первоначальная загрузка при старте модуля
load_countries()
# =========================================================================


def get_meta_by_country(country_name: str) -> tuple[str, str]:
    """
    Вернуть (телефонный код, маску) по названию страны на любом из 6 языков.
    Если страна не найдена — ('+', '__________').
    """
    return (
        PHONE_CODE.get(country_name, "+"),
        PHONE_MASK.get(country_name, "__________"),
    )


def is_cis(country: str, lang: str) -> bool:
    return country in CIS_SET.get(lang, set())
