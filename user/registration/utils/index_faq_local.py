# === file: index_faq_local.py =================================================
from pathlib import Path
import pandas as pd
from tqdm.auto import tqdm
from langchain_community.embeddings import SentenceTransformerEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.docstore.document import Document

# ── 1. Конфигурация ───────────────────────────────────────
XLSX = Path(__file__).parent / "excel" / "info_for_rag.xlsx"
INDEX_DIR = Path(__file__).parent / "faiss_index"
LANGS = ["ru", "en", "es", "fr", "pt", "ar"]


def build_faiss_index(
    xlsx_path: Path = XLSX,
    index_dir: Path = INDEX_DIR,
    langs: list[str] = LANGS,
) -> None:
    """
    Считывает данные из xlsx_path, строит FAISS-индекс и сохраняет его в index_dir.
    Можно вызывать многократно во время работы приложения для 'горячей' перезагрузки индекса.
    """
    # 1. Проверяем наличие исходного файла
    if not xlsx_path.exists():
        raise FileNotFoundError(f"{xlsx_path} не найден")

    # 2. Читаем Excel
    df = pd.read_excel(xlsx_path)
    question_cols = df.columns[: len(langs)]
    answer_cols = df.columns[len(langs) : len(langs) * 2]

    # 3. Настраиваем эмбеддинги
    emb = SentenceTransformerEmbeddings(
        model_name="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        model_kwargs={"device": "cpu"},
    )

    # 4. Формируем список документов (Document) для индексирования
    docs: list[Document] = []
    for _, row in tqdm(df.iterrows(), total=len(df), desc="Building docs"):
        for lang, q_col, a_col in zip(langs, question_cols, answer_cols):
            q = row[q_col]
            a = row[a_col]
            if pd.isna(q) or pd.isna(a):
                continue
            docs.append(
                Document(
                    page_content=str(q),
                    metadata={"lang": lang, "answer": str(a)},
                )
            )

    # 5. Строим FAISS-индекс
    vectordb = FAISS.from_documents(docs, embedding=emb)

    # 6. Убеждаемся, что папка для индекса существует
    index_dir.mkdir(parents=True, exist_ok=True)

    # 7. Сохраняем индекс на диск
    vectordb.save_local(str(index_dir))

    print(f"✓ FAISS index saved to {index_dir}. Documents: {len(docs)}")


# При импорте модуля сразу строим индекс для первого запуска
build_faiss_index()
