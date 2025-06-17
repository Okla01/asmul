from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from admins.registration.states import AdminRegistration
from db.database import get_user_registrations, set_user_role, get_user_role
from config import report_questions_from_candidates_chat_id
from admins.keyboards import (
    get_practice_supervisor_panel_kb,
    get_admin_panel_kb,
    get_superadmin_panel_kb
)

router = Router()

@router.message(AdminRegistration.WaitingForFIO)
async def process_fio(message: Message, state: FSMContext):
    # Записываем ФИО в состояние
    await state.update_data(fio=message.text)
    
    # Получаем целевую роль из состояния
    state_data = await state.get_data()
    target_role = state_data.get("target_role")
    
    # Отправляем сообщение в чат администраторов
    await message.bot.send_message(
        report_questions_from_candidates_chat_id,
        f"Новая заявка на регистрацию администратора\n"
        f"Пользователь: {message.from_user.mention_markdown()}\n"
        f"Роль: {target_role}\n"
        f"ФИО: {message.text}\n"
        f"\n"
        f"{message.from_user.url}",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="✅ Одобрить",
                        callback_data=f"approve_admin:{message.from_user.id}:{target_role}"
                    ),
                    types.InlineKeyboardButton(
                        text="❌ Отклонить",
                        callback_data=f"reject_admin:{message.from_user.id}:{target_role}"
                    )
                ]
            ]
        )
    )
    
    # Переходим в состояние ожидания одобрения
    await state.set_state(AdminRegistration.WaitingForApproval)
    
    await message.answer(
        "✅ Ваша заявка на регистрацию отправлена!\n"
        "Ожидайте решения администраторов."
    )

@router.callback_query(F.data.startswith("approve_admin:"))
async def approve_admin(callback: CallbackQuery, state: FSMContext):
    _, user_id_str, role = callback.data.split(":", 2)
    user_id = int(user_id_str)
    
    set_user_role(user_id, role)
    
    await callback.message.edit_text(
        f"Заявка на регистрацию одобрена!\n"
        f"Пользователь: {callback.from_user.mention_markdown()}\n"
        f"Роль: {role}"
    )
    
    await callback.bot.send_message(
        user_id,
        f"✅ Ваша заявка на регистрацию одобрена!\n"
        f"Теперь вы зарегистрированы как {role}.\n"
        f"Для доступа к панели введите /{role.split('_')[1]}"
    )

@router.callback_query(F.data.startswith("reject_admin:"))
async def reject_admin(callback: CallbackQuery, state: FSMContext):
    _, user_id_str, role = callback.data.split(":", 2)
    user_id = int(user_id_str)
    
    await callback.message.edit_text(
        f"Заявка на регистрацию отклонена!\n"
        f"Пользователь: {callback.from_user.mention_markdown()}"
    )
    
    await callback.bot.send_message(
        user_id,
        "❌ Ваша заявка на регистрацию отклонена.\n"
        "Обратитесь к администраторам для получения дополнительной информации."
    )
