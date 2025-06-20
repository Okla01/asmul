from math import ceil

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import PHOTO_CIS, PHOTO_WORLD
from db.database import has_photo, has_passport, has_both_sims
from user.registration.utils.countries import *
from user.registration.utils.info import INFO_DATA, PAGE_SIZE
from user.registration.utils.locale_to_excel import TRANSLATIONS, ensure_up_to_date


def tr(lang: str, key: str, **kwargs) -> str:
    """
    Возвращает перевод строки `key` для языка `lang`.
    Автоматически перечитывает Excel, если файл был изменён.
    """
    ensure_up_to_date()
    if lang not in TRANSLATIONS:
        TRANSLATIONS[lang] = {}

    if key in TRANSLATIONS[lang]:
        return TRANSLATIONS[lang][key].format(**kwargs)

    # fallback: русский
    return TRANSLATIONS["ru"].get(key, key).format(**kwargs)


def stage2_intro_text(lang: str, user_id: int) -> str:
    mark = lambda ok: "✅" if ok else "⬜️"
    return tr(
        lang,
        "stage2_intro",
        photo=mark(has_photo(user_id)),
        passport=mark(has_passport(user_id)),
        sim=mark(has_both_sims(user_id)),
    )


def get_photo_example_url(country: str, lang: str) -> str:
    return PHOTO_CIS if is_cis(country, lang) else PHOTO_WORLD


# ------------------------------------------------------------------
# 3.  КЛАВИАТУРЫ
# ------------------------------------------------------------------
def build_lang_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Русский", callback_data="lang_ru")
    kb.button(text="English", callback_data="lang_en")
    kb.button(text="Español", callback_data="lang_es")
    kb.button(text="Français", callback_data="lang_fr")
    kb.button(text="Português", callback_data="lang_pt")
    kb.button(text="العربية", callback_data="lang_ar")
    return kb.adjust(1).as_markup()


LANG_KB = build_lang_kb()  # готовая «выбор языка»


# --- общая заготовка-хелпер ---------------------------------------
def _kb_single(text: str, cb: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=text, callback_data=cb)
    return kb.as_markup()


# ---------- шаг «Вы участница / стать участницей» -----------------
def build_participant_kb(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=tr(lang, "btn_become_participant"), callback_data="become_participant")
    return kb.as_markup()


# ---------- выбор пола --------------------------------------------
def build_gender_kb(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=tr(lang, "btn_gender_male"), callback_data="gender_male")
    kb.button(text=tr(lang, "btn_gender_female"), callback_data="gender_female")
    return kb.as_markup()


def build_gender_male_kb(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=tr(lang, "btn_back"), callback_data="delete_this_msg_cand")
    kb.button(text=tr(lang, "btn_support_contacts"), callback_data="btn_support_contacts")
    return kb.adjust(2).as_markup()


# ---------- подтверждение данных ----------------------------------
def build_apply_reg_kb(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=tr(lang, "btn_confirm"), callback_data="confirm_registration")
    kb.button(text=tr(lang, "btn_change"), callback_data="change_data")
    return kb.adjust(2).as_markup()


# ---------- меню Stage 2 ------------------------------------------
def build_stage2_kb(lang: str, completed: bool = False):
    kb = InlineKeyboardBuilder()
    if not completed:  # ← показываем загрузочные пункты,
        kb.button(text=tr(lang, "btn_send_photo"), callback_data="go_stage_2.1")
        kb.button(text=tr(lang, "btn_attach_passport"), callback_data="go_stage_2.2")
        kb.button(text=tr(lang, "btn_pass_simulation"), callback_data="go_stage_2.3")
    # ─ эти две кнопки нужны всегда ─
    kb.button(text=tr(lang, "btn_more_info"), callback_data="go_stage_3")
    kb.button(text=tr(lang, "btn_question"), callback_data="go_stage_2.4")
    return kb.adjust(1).as_markup()


# ---------- «Назад» / «Продолжить» и др. ---------------------------
def build_stage2_1_back_kb(lang: str):
    return _kb_single(tr(lang, "btn_back"), "go_stage_2")


def build_stage2_1_continue_kb(lang: str):
    return _kb_single(tr(lang, "btn_continue"), "go_stage_2")


def build_back_1_1_kb(lang: str):
    return _kb_single(tr(lang, "btn_back"), "back_1_1")


# ---------- «Есть / нет паспорта» ---------------------------------
def build_passport_choice_kb(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=tr(lang, "btn_has_passport"), callback_data="has_passport")
    kb.button(text=tr(lang, "btn_no_passport"), callback_data="no_passport")
    kb.button(text=tr(lang, "btn_back"), callback_data="go_stage_2")
    return kb.adjust(1).as_markup()


# ---------- причины отсутствия паспорта ----------------------------
def build_passport_reason_kb(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=tr(lang, "btn_reason_wait"), callback_data="reason_wait")
    kb.button(text=tr(lang, "btn_reason_money"), callback_data="reason_money")
    kb.button(text=tr(lang, "btn_reason_other"), callback_data="reason_other")
    return kb.adjust(1).as_markup()


# ---------- симуляции АС / ВС -------------------------------------
def build_sim_as_vs_kb(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=tr(lang, "btn_sim_as"), callback_data="sim_as")
    kb.button(text=tr(lang, "btn_sim_vs"), callback_data="sim_vs")
    kb.button(text=tr(lang, "btn_back"), callback_data="go_stage_2")
    return kb.adjust(1).as_markup()


# ---------- финальная проверка ------------------------------------
def build_final_stage_kb(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=tr(lang, "btn_final_confirm"), callback_data="final_confirm")
    kb.button(text=tr(lang, "btn_back"), callback_data="back_to_passport_choice")
    return kb.adjust(1).as_markup()


# ──────────────────────────────────────────────────────────────
#  Кнопка «Отмена» (пока юзер формулирует вопрос)
# ──────────────────────────────────────────────────────────────
def build_cancel_question_kb(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=tr(lang, "btn_cancel"), callback_data="cancel_question")
    return kb.adjust(1).as_markup()


# ──────────────────────────────────────────────────────────────
#  Кнопка «Вернуться в меню» после отправки вопроса
# ──────────────────────────────────────────────────────────────
def build_back_to_menu_kb(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=tr(lang, "btn_back_to_menu"), callback_data="go_stage_2")
    return kb.adjust(1).as_markup()


# ──────────────────────────────────────────────────────────────
#  Кнопка «Ответить» для админ‑чата
# ──────────────────────────────────────────────────────────────
def get_admin_reply_kb(user_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✉️ Ответить", callback_data=f"admin_reply_cand_{user_id}")
    return kb.adjust(1).as_markup()


# ───────────────── меню «Полезная информация» с пагинацией ─────────

def build_info_menu_kb(lang: str, page: int = 0):
    items = INFO_DATA.get(lang, [])
    if not items:
        return _kb_single(tr(lang, "btn_back"), "go_stage_2")

    pages = ceil(len(items) / PAGE_SIZE)
    page = max(0, min(page, pages - 1))

    start, end = page * PAGE_SIZE, (page + 1) * PAGE_SIZE
    kb = InlineKeyboardBuilder()

    # ——— пункты меню, по 2 в строке ———
    for idx, (title, _) in enumerate(items[start:end], start=start):
        kb.row(InlineKeyboardButton(text=title[:60],
                                    callback_data=f"info_show_{idx}_{page}"))

    # ——— навигация: ◀ x/y ▶ (круговая) ———
    prev_page = page - 1 if page > 0 else pages - 1
    next_page = page + 1 if page < pages - 1 else 0

    kb.row(
        InlineKeyboardButton(text=tr(lang, "btn_prev"), callback_data=f"info_page_{prev_page}"),
        InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="info_nop"),
        InlineKeyboardButton(text=tr(lang, "btn_next"), callback_data=f"info_page_{next_page}"),
    )

    # нижняя строка «Назад»
    kb.row(InlineKeyboardButton(text=tr(lang, "btn_back"),
                                callback_data="go_stage_2"))

    return kb.as_markup()


def build_back_to_info_kb(lang: str, page: int):
    kb = InlineKeyboardBuilder()
    kb.button(text=tr(lang, "btn_back_to_list"), callback_data=f"info_page_{page}")
    return kb.as_markup()


def build_country_kb(lang: str, page: int = 0):
    items = COUNTRY_LIST.get(lang, [])
    kb = InlineKeyboardBuilder()

    start = page * PAGE_SIZE_COUNTRY
    end = start + PAGE_SIZE_COUNTRY

    # кнопки со странами
    for idx, name in enumerate(items[start:end], start=start):
        kb.button(text=name, callback_data=f"country_sel_{idx}")

    # навигационные стрелки
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text=tr(lang, "btn_prev"),
            callback_data=f"country_pg_{page - 1}"
        ))
    if end < len(items):
        nav.append(InlineKeyboardButton(
            text=tr(lang, "btn_next"),
            callback_data=f"country_pg_{page + 1}"
        ))
    if nav:
        kb.row(*nav)

    return kb.adjust(1).as_markup()


def build_phone_kb(code: str, lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(
        text="📞 " + tr(lang, "label_phone"),
        switch_inline_query_current_chat=f"phone: {code} "
    )

    return kb.adjust(1).as_markup()


def delete_this_msg_cand(lang: str):
    kb = InlineKeyboardBuilder()
    kb.button(text=tr(lang, "btn_close"), callback_data="delete_this_msg_cand")
    kb = kb.as_markup()
    return kb


def build_country_search_kb(lang: str):
    """
    Одна кнопка: «🔍 Найти страну» — запускает inline‑поиск с префиксом country:
    + «Назад» (к выбору пола).
    """
    kb = InlineKeyboardBuilder()
    kb.button(text="🔍 " + tr(lang, "label_country"),  # 🔍 Страна / Country / …
              switch_inline_query_current_chat="country: ")
    return kb.adjust(1).as_markup()


def get_claim_kb(user_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Взять заявку", callback_data=f"admin_claim_user_{user_id}")
    return kb.adjust(1).as_markup()
