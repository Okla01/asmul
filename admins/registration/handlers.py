from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from admins.registration.states import AdminRegistration
from db.database import get_user_registrations, set_user_role
from config import report_questions_from_candidates_chat_id

router = Router()

# Команды для регистрации
REGISTRATION_COMMANDS = {
    "super_admin_reg": "admin_supervisor",
    "admin_reg": "admin_admin",
    "ruk_pract_reg": "admin_practice_supervisor"
}

@router.message(F.text.startswith("/"), lambda m: m.text[1:] in REGISTRATION_COMMANDS.keys())
async def admin_registration_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Проверяем наличие незавершённых заявок администратора
    registrations = get_user_registrations(user_id)
    pending_registrations = [reg for reg in registrations if reg["status"] == "pending"]
    
    if pending_registrations:
        await message.answer(
            "❗ У вас уже есть незавершённая заявка на регистрацию.\n"
            "Ожидайте решения администраторов."
        )
        return
    
    # Определяем целевую роль
    target_role = REGISTRATION_COMMANDS[message.text[1:]]
    
    # Устанавливаем стейт и запрашиваем ФИО
    await state.set_state(AdminRegistration.WaitingForFIO)
    await state.update_data(target_role=target_role)
    
    await message.answer(
        "Для регистрации введите своё ФИО:\n"
        "(Фамилия Имя Отчество)"
    )

@router.message(AdminRegistration.WaitingForFIO)
async def process_fio(message: Message, state: FSMContext):
    fio = message.text.strip()
    
    # Валидация ФИО
    if not fio or len(fio.split()) < 2:
        await message.answer(
            "Пожалуйста, введите корректное ФИО в формате:\n"
            "Фамилия Имя Отчество"
        )
        return
    
    # Сохраняем данные и отправляем заявку на одобрение
    await state.update_data(fio=fio)
    
    # Получаем данные из стейта
    data = await state.get_data()
    target_role = data["target_role"]
    
    # Проверяем, существует ли чат для отправки заявки
    try:
        chat_info = await message.bot.get_chat(report_questions_from_candidates_chat_id)
    except Exception as e:
        await message.answer(
            "❌ Произошла ошибка при отправке заявки.\n"
            "Пожалуйста, сообщите администратору о проблеме."
        )
        await state.clear()
        return
    
    # Формируем текст заявки
    admin_text = (
        f"Новая заявка на регистрацию администратора:\n\n"
        f"ФИО: {fio}\n"
        f"Роль: {target_role}\n\n"
        f"ID пользователя: {message.from_user.id}\n"
        f"Username: @{message.from_user.username if message.from_user.username else 'не указан'}"
    )
    
    # Отправляем заявку в чат администраторов
    try:
        admin_msg = await message.bot.send_message(
            chat_id=report_questions_from_candidates_chat_id,
            text=admin_text,
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
    except Exception as e:
        await message.answer(
            "❌ Произошла ошибка при отправке заявки.\n"
            "Пожалуйста, сообщите администратору о проблеме."
        )
        await state.clear()
        return
    
    await message.answer(
        "✅ Ваша заявка на регистрацию отправлена администраторам.\n"
        "Ожидайте решения."
    )
    await state.clear()

@router.callback_query(F.data.startswith("approve_admin:"))
async def approve_admin(callback: CallbackQuery, state: FSMContext):
    _, user_id_str, role = callback.data.split(":", 2)
    user_id = int(user_id_str)
    
    # Устанавливаем роль пользователю
    set_user_role(user_id, role)
    
    # Обновляем сообщение в чате администраторов
    await callback.message.edit_text(
        f"Заявка на регистрацию одобрена!\n"
        f"Пользователь: {callback.from_user.mention_markdown()}\n"
        f"Роль: {role}"
    )
    
    # Уведомляем пользователя
    user = await callback.bot.get_chat(user_id)
    await user.send_message(
        f"✅ Ваша заявка на регистрацию одобрена!\n"
        f"Теперь вы зарегистрированы как {role}.\n"
        f"Для доступа к панели введите /admin"
    )

@router.callback_query(F.data.startswith("reject_admin:"))
async def reject_admin(callback: CallbackQuery, state: FSMContext):
    _, user_id_str, role = callback.data.split(":", 2)
    user_id = int(user_id_str)
    
    # Обновляем сообщение в чате администраторов
    await callback.message.edit_text(
        callback.message.text + "\n\n❌ Заявка отклонена",
        reply_markup=None
    )
    
    # Уведомляем пользователя
    await callback.bot.send_message(
        user_id,
        "❌ Ваша заявка на регистрацию отклонена.\n"
        "Для повторной подачи заявки введите команду регистрации."
    )
    
    await callback.answer("Заявка отклонена")

@router.message(Command("check_registration_status"))
async def check_registration_status(message: Message):
    """Показывает статус всех заявок пользователя на регистрацию."""
    user_id = message.from_user.id
    
    registrations = get_user_registrations(user_id)
    if not registrations:
        await message.answer(
            "У вас нет заявок на регистрацию.\n"
            "Для подачи заявки используйте команды:\n"
            "/super_admin_reg - заявка на суперадминистратора\n"
            "/admin_reg - заявка на администратора\n"
            "/ruk_pract_reg - заявка на руководителя практики"
        )
        return
    
    text = "Ваши заявки на регистрацию:\n\n"
    for reg in registrations:
        status_emoji = {
            "pending": "⏳",
            "approved": "✅",
            "rejected": "❌"
        }.get(reg["status"], "❓")
        
        approved_by = f" (одобрил: {reg['approved_by']})" if reg["approved_by"] else ""
        comment = f"\nКомментарий: {reg['comment']}" if reg["comment"] else ""
        
        text += (f"{status_emoji} Роль: {reg['target_role']}\n"
                 f"ФИО: {reg['fio']}\n"
                 f"Статус: {reg['status']} {approved_by}\n"
                 f"Дата: {reg['created_at']}"
                 f"{comment}\n\n")
    
    await message.answer(text)
