import argparse, random
import inspect
from pathlib import Path
from typing import List, Tuple
import numpy as np, pandas as pd
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.docstore.document import Document
from sentence_transformers import CrossEncoder
from tqdm.auto import tqdm
from pymorphy3 import MorphAnalyzer

try:
    import regex as re

    TOKEN_RE = re.compile(r"\p{L}+|\d+", re.IGNORECASE)
except ModuleNotFoundError:
    import re  # type: ignore

    TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё\d]+", re.IGNORECASE)

morph = MorphAnalyzer()


def _lemma(t: str) -> str:
    if len(t) <= 3:
        return t  # мелочь не трогаем
    return morph.parse(t)[0].normal_form


def _tokens(text: str) -> set[str]:
    raw = {m.group(0).lower() for m in TOKEN_RE.finditer(text)}
    return {_lemma(t) for t in raw}


SMALL_TALK_PATTERNS: tuple[str, ...] = (
    # ─ приветствия
    r"^\s*(привет|здра[вв]ствуй|здор[оа]во|салют|хай)\b",
    r"^\s*добро[еия]\s+(утро|время|день|вечер)\b",
    r"^\s*(hello|hi|hey|good\s+(morning|afternoon|evening))\b",

    # ─ вопрос «как дела»
    r"\bкак\s+(дела|ты|жизнь|оно|life|it\s+going)\b",

    # ─ «что нового»
    r"\bч(е|т)о\s+нов(ого|енького)\b",
    r"\bwhat'?s?\s+up\b",

    # ─ поболтать / смолтолк
    r"\b(чем\s+занят|how\s+are\s+you\s+doing)\b",

    # ─ благодарность / прощание как отдельное сообщение
    r"^\s*(спасибо|thanks|thank\s+you)\b",
    r"^\s*(пока|bye|see\s+you)\b",
)

_small_re = [re.compile(pat, re.IGNORECASE) for pat in SMALL_TALK_PATTERNS]
def _is_small_talk(text: str) -> bool:
    text = text.strip().lower()
    if len(_tokens(text)) <= 2:        # одно-два слова → почти всегда болтовня
        return True
    return any(rx.search(text) for rx in _small_re)


def _lexical_overlap_ext(q: str, ref: str, best: float, margin: float) -> bool:
    inter = _tokens(q) & _tokens(ref)
    good = {t for t in inter if len(t) >= 2}
    if best >= 0.90 and margin >= 0.20:
        return True
    if len(good) >= 2:
        return True
    # high‑confidence back‑off
    if len(good) == 1 and best >= 0.65 and margin >= 0.15:
        return True
    return False


# ───────── constants ─────────
ROOT = Path(__file__).parent
XLSX = Path(__file__).parent / "excel" / "info_for_rag.xlsx"
INDEX_DIR = ROOT / "faiss_index"
LANGS = ["", "ru", "en", "es", "fr", "pt", "ar"]
EMB_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
ABS_TH, REL_DIFF, K = 0.35, 0.10, 15
NEG_QUERIES_DEFAULT: List[str] = [
    "привет", "как дела", "ты кто", "скажи анекдот", "что нового",
    "hello", "tell me a joke", "how's the weather", "sing a song",
    "сколько времени", "я люблю пиццу", "make me a coffee", "??",
]


# ───────── indexing ─────────

def _build_index():
    if INDEX_DIR.exists():
        emb = SentenceTransformerEmbeddings(model_name=EMB_MODEL, model_kwargs={"device": "cpu"})
        return FAISS.load_local(str(INDEX_DIR), emb, allow_dangerous_deserialization=True)
    df = pd.read_excel(XLSX)
    q_cols, a_cols = df.columns[:len(LANGS)], df.columns[len(LANGS):2 * len(LANGS)]
    docs: List[Document] = []
    for _, row in tqdm(df.iterrows(), total=len(df), desc="xlsx rows"):
        for lang, q, a in zip(LANGS, row[q_cols], row[a_cols]):
            if pd.isna(q) or pd.isna(a): continue
            docs.append(Document(page_content=str(q), metadata={"lang": lang, "answer": str(a)}))
    emb = SentenceTransformerEmbeddings(model_name=EMB_MODEL, model_kwargs={"device": "cpu"})
    vdb = FAISS.from_documents(docs, emb)
    vdb.save_local(str(INDEX_DIR))
    return vdb


# ───────── engine ─────────
class RagEngine:
    def __init__(self, abs_th: float = ABS_TH, rel_diff: float = REL_DIFF, k: int = K):
        self.abs_th, self.rel_diff, self.k = abs_th, rel_diff, k
        self.vdb = _build_index()
        self.ret = self.vdb.as_retriever(search_kwargs={"k": k})
        self.rerank = CrossEncoder(RERANK_MODEL, device="cpu")

    def ask(self, query: str, lang: str = "ru") -> Tuple[str | None, float | None]:
        if _is_small_talk(query):
            return None, None
        if len(_tokens(query)) < 2 or _is_small_talk(query): return None, None
        docs = self.ret.get_relevant_documents(query, filter={"lang": lang}, k=self.k)
        if len(docs) < 2: return None, None
        scores = self.rerank.predict([[query, d.page_content] for d in docs])
        order = scores.argsort()[::-1]
        best_i, second_i = int(order[0]), int(order[1])
        best, second = float(scores[best_i]), float(scores[second_i])
        if (best < self.abs_th) or (best - second < self.rel_diff): return None, None
        full_text = docs[best_i].page_content + ' ' + docs[best_i].metadata["answer"]
        if not _lexical_overlap_ext(query, full_text, best, best - second):
            return None, None
        return docs[best_i].metadata["answer"], best


# ───────── CLI ─────────
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true")
    args = ap.parse_args()
    eng = RagEngine()
    if args.calibrate:
        pos = [d.page_content for d in eng.vdb.docstore._dict.values() if d.metadata["lang"] == "ru"]
        neg = NEG_QUERIES_DEFAULT
        print("thr | recall |  FPR\n────|────────|──────")
        for thr in [0.4, 0.5, 0.6]:
            tmp = RagEngine(abs_th=thr)
            rec = sum(tmp.ask(q)[0] is not None for q in pos) / len(pos)
            fpr = sum(tmp.ask(q)[0] is not None for q in neg) / len(neg)
            print(f"{thr:.2f}|  {rec:5.2%} | {fpr:5.2%}")

# ───────── tests ─────────
import pytest


@pytest.fixture(scope="session")
def engine(): return RagEngine()


def test_index_size(engine): assert len(engine.vdb.docstore._dict) >= 100


def test_recall(engine):
    random.seed(0)
    ru_q = [d.page_content for d in engine.vdb.docstore._dict.values() if d.metadata["lang"] == "ru"]
    sample = random.sample(ru_q, 20)
    hits = sum(engine.ask(q)[0] is not None for q in sample)
    assert hits / len(sample) >= 0.8


def test_false_positive_rate(engine):
    fp = sum(engine.ask(q)[0] is not None for q in NEG_QUERIES_DEFAULT)
    fpr = fp / len(NEG_QUERIES_DEFAULT)
    assert fpr <= 0.08, f"FPR too high: {fpr:.2%}"
