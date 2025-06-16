import re
from hashlib import md5
from typing import Tuple

from user.registration.utils.countries import get_meta_by_country


def build_phone_display(code: str, digits: str, mask: str) -> str:
    """
    "+" код + "___ __ ___‑__‑__"   → "+7 912 34 567‑89‑01"
    "+" код + "### ## ###‑##‑##"  → "+7 912 34 567‑89‑01"
    """
    filled, d_iter = [], iter(digits)
    for ch in mask:
        filled.append(next(d_iter, "_") if ch in "_#" else ch)   # ← заменяем и '_' и '#'
    return f"{code} {''.join(filled)}".strip()


def safe_result_id(code: str, digits: str) -> str:
    """
    Генерирует ASCII‑id ≤ 64 симв.  пример: 'ph_7_9123_4e5f6a7b'
    """
    raw = f"{code}_{digits or 'empty'}"
    return f"ph_{md5(raw.encode()).hexdigest()[:10]}"
# ==================================================================
