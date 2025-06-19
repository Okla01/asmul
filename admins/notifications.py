from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import config

async def notify_admins_about_ps_request(
    req_id: int,
    user_id: int,
    username: str,
    full_name: str,
    department: str
):
    """Отправляет уведомление администраторам о новой заявке на регистрацию РП"""
    bot = Bot.get_current()
    admin_chat_id = config.request_bot_user_chat_id
    
    if not admin_chat_id:
        print("Ошибка: не указан chat_id для отправки уведомлений администраторам")
        return
    
    # Создаем кнопки для одобрения/отклонения
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Одобрить",
            callback_data=f"ps_approve:{req_id}"  # req_id должен быть числом
        ),
        InlineKeyboardButton(
            text="❌ Отклонить",
            callback_data=f"ps_reject:{req_id}"
        )
    ]])
    
    # Формируем текст сообщения
    text = (
        f"📋 <b>Новая заявка на регистрацию руководителя практики</b>\n\n"
        f"👤 <b>ФИО:</b> {full_name}\n"
        f"🏢 <b>Подразделение:</b> {department}\n"
        f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
        f"👤 <b>Username:</b> @{username or 'не указан'}\n"
        f"🔢 <b>ID заявки:</b> <code>{req_id}</code>"
    )
    
    try:
        await bot.send_message(
            chat_id=admin_chat_id,
            text=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Ошибка при отправке уведомления администраторам: {e}")
