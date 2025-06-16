# llm_answer.py  •  RAG-контекст (4 документа) → GigaChat
# ──────────────────────────────────────────────────────────────
from __future__ import annotations

from html import escape
import numpy as np

from aiogram.types import Message
from aiogram.exceptions import TelegramForbiddenError

from config import bot, report_questions_from_candidates_chat_id, GIGA_TOKEN
from db.database import get_user_lang
from user.registration.keyboards import (
    get_admin_reply_kb,
    tr,
    build_back_to_menu_kb,
)
from user.registration.utils.bad_words import contains_profanity
from user.registration.utils.rag_engine import RagEngine

from langchain_gigachat.chat_models import GigaChat
from langchain_core.prompts import PromptTemplate

# ── инициализация ─────────────────────────────────────────────
engine = RagEngine()
TOP_N_CONTEXT = 4  # в prompt идёт ровно 4 документа

llm = GigaChat(
    credentials=GIGA_TOKEN,
    model="GigaChat-2",
    verify_ssl_certs=False,
    scope="GIGACHAT_API_PERS",
    max_tokens=700,
    temperature=0.1,
)

PROMPT = PromptTemplate(
    template="""
<SYSTEM>
Ты — виртуальный помощник «Алабуга Старт».
Отвечай КРАТКО и ТОЛЬКО фактами из CONTEXT, и ТОЛЬКО НА ЯЗЫКЕ ВОПРОСА.
Если в CONTEXT нет ответа — напиши: «Не нашла информации в FAQ».
Если вопрос не связан с «Алабуга Старт» — тоже так и напиши.
В конце добавляй строку: «Сгенерировано нейросетью, пожалуйста, перепроверяйте информацию в FAQ».
[/SYSTEM]

[CONTEXT]
{context}
[/CONTEXT]

[USER]
{question}
[/USER]
[ASSISTANT]""",
    input_variables=["context", "question"],
)


# ── утилиты для администрации ────────────────────────────────
async def _forward_to_admin(msg: Message, q: str, lang: str) -> None:
    try:
        await bot.forward_message(
            report_questions_from_candidates_chat_id,
            msg.chat.id,
            msg.message_id,
        )
    except TelegramForbiddenError:
        pass

    await bot.send_message(
        report_questions_from_candidates_chat_id,
        "❓ <b>Вопрос от пользователя</b>\n\n"
        f"{escape(msg.from_user.full_name)}"
        + (f" (@{msg.from_user.username})" if msg.from_user.username else "")
        + f"\nID: {msg.from_user.id}\n\n<b>Вопрос:</b>\n{escape(q)}",
        parse_mode="HTML",
        reply_markup=get_admin_reply_kb(msg.from_user.id),
    )

    await bot.send_message(
        msg.chat.id,
        tr(lang, "ask_sent"),
        reply_markup=build_back_to_menu_kb(lang),
    )


# ── формируем CONTEXT (4 лучших FAQ-пункта) ───────────────────
def _make_context(query: str, lang: str) -> str:
    """
    • выбираем k≈8 кандидатов через FAISS,
    • ранжируем Cross-Encoder’ом из RagEngine,
    • оставляем TOP_N_CONTEXT лучших.
    Возвращаем строку для вставки в prompt.
    """
    k_fetch = TOP_N_CONTEXT * 2
    docs = engine.ret.get_relevant_documents(query, filter={"lang": lang}, k=k_fetch)
    if not docs:
        return ""

    scores = engine.rerank.predict([[query, d.page_content] for d in docs])
    order = np.argsort(scores)[::-1][:TOP_N_CONTEXT]

    ctx_parts: list[str] = []
    for idx in order:
        d = docs[int(idx)]
        q = d.page_content.strip()
        a = d.metadata["answer"].strip()
        ctx_parts.append(f"Q: {q}\nA: {a}")

    return "\n\n".join(ctx_parts)


# ── главный обработчик сообщения ─────────────────────────────
async def answer(message: Message) -> None:
    text = (message.text or "").strip()
    user_lang = get_user_lang(message.from_user.id)

    # 0) фильтр мата
    if contains_profanity(text):
        try:
            await message.delete()
        except Exception:
            pass
        return

    # 1) быстрый ранжировщик: есть ли релевантный пункт FAQ?
    faq_answer, _score = engine.ask(text, user_lang)
    if faq_answer is None:  # ничего релевантного
        await _forward_to_admin(message, text, user_lang)
        return

    # 2) готовим контекст (ровно 4 документа) и вызываем GigaChat
    context = _make_context(text, user_lang)
    llm_prompt = PROMPT.format(context=context, question=text)

    try:
        llm_raw = llm.invoke(llm_prompt)  # → AIMessage
    except Exception:
        llm_raw = llm.invoke(llm_prompt)  # повтор (редко сети)
    llm_answer = llm_raw.content.strip()

    # 3) если LLM ответила заглушкой — отдаём первый FAQ-документ
    fallback = "не нашла информации в faq"
    final_text = faq_answer if fallback in llm_answer.lower() else llm_answer

    await bot.send_message(
        message.chat.id,
        final_text,
        reply_markup=build_back_to_menu_kb(user_lang),
    )
