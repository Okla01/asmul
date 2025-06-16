# bad_words.py ─────────────────────────────────────────────────
from __future__ import annotations
import json, re, time
from pathlib import Path
from urllib.request import urlopen
from functools import lru_cache

URL = "https://raw.githubusercontent.com/thisandagain/washyourmouthoutwithsoap/develop/data/build.json"
CACHE_FILE = Path(__file__).with_name("bad_words_cache.json")

# 🚩 свой список русского мата (минимальный; расширяйте при необходимости)
RU_EXTRA = {
    "хрен", "хрена", "бляд", "бля", "сука", "суки", "сукин", "пизд", "сосал",
    "еба", "ёба", "ёб", "еб", "нахрен", "нахер", "нахуй", "хуй", "пизда", "член"
}

LANGS_KEEP = {"en", "es", "fr", "pt", "ar"}  # из build.json


# ──────────────────────────────────────────────────────────────
def _download() -> dict[str, list[str]]:
    with urlopen(URL, timeout=10) as r:
        return json.load(r)


def _load() -> dict[str, list[str]]:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text("utf-8"))
    data = _download()
    CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    return data


@lru_cache(maxsize=None)
def _regex() -> re.Pattern[str]:
    data = _load()

    patterns: list[str] = []
    # языки из build.json
    for lang, words in data.items():
        if lang not in LANGS_KEEP:
            continue
        patterns.extend(re.escape(w) for w in words if w)

    # наш русский список (+ все формы через а-яё*)
    patterns.extend(fr"{re.escape(w)}[а-яё]*" for w in RU_EXTRA)

    # (?iu) – ignorecase + unicode; \b слева и справа
    return re.compile(r"(?iu)\b(" + "|".join(patterns) + r")\b")


# ── публичная функция ────────────────────────────────────────
def contains_profanity(text: str) -> bool:
    return _regex().search(text) is not None


# ── тест ─────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        "hello world",
        "fuck you",
        "какого хрена",
        "нахрен мне это",
        "приятного вечера",
    ]
    for t in tests:
        print(f"{t!r} → {contains_profanity(t)}")
