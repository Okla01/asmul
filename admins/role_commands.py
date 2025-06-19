from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from db.database import get_user_role, set_user_role, get_user_registrations
from config import report_questions_from_candidates_chat_id

from admins.registration.states import AdminRegistration
from admins.keyboards import get_practice_supervisor_panel_kb, get_admin_panel_kb, get_superadmin_panel_kb
from admins.practice_supervisor.registration.keyboards import get_ps_register_kb

router = Router()

# Команды для ролей
ROLE_COMMANDS = {
    "supervisor": "admin_supervisor",
    "admin": "admin_admin",
    "practice": "admin_practice_supervisor"
}

@router.message(Command(commands=list(ROLE_COMMANDS.keys())))
async def role_command(message: Message, state: FSMContext) -> None:
    """Обработка команд /admin, /supervisor, /practice и др."""
    user_id = message.from_user.id
    command = message.text.lstrip("/")          # без слэша

    # 👉 1. Проверяем текущую роль
    current_role = get_user_role(user_id)
    if current_role == ROLE_COMMANDS[command]:
        await open_role_panel(message, current_role)
        return

    # 👉 2. Есть ли незавершённые заявки на ЭТУ роль?
    registrations = get_user_registrations(user_id)
    pending_registrations = [
        reg for reg in registrations
        if reg["status"] == "pending" and reg["target_role"] == ROLE_COMMANDS[command]
    ]
    if pending_registrations:
        await message.answer(
            f"❗ У вас уже есть незавершённая заявка на регистрацию {command}.\n"
            "Ожидайте решения администраторов."
        )
        return

    # 👉 3. Спец-поведение для /practice — показываем кнопку вместо запроса ФИО
    if command == "practice":
        await message.answer(
            "У вас пока нет роли руководителя практики.\n"
            "Нажмите кнопку ниже, чтобы подать заявку:",
            reply_markup=get_ps_register_kb(),
        )
        return

    # 👉 4. Для остальных ролей: запрашиваем ФИО
    await state.set_state(AdminRegistration.WaitingForFIO)
    await state.update_data(target_role=ROLE_COMMANDS[command])

    await message.answer(
        "Для регистрации введите своё ФИО:\n"
        "(Фамилия Имя Отчество)"
    )


async def open_role_panel(message: Message, role: str):
    """Открывает панель администратора в зависимости от роли."""
    if role == "admin_practice_supervisor":
        await message.answer(
            "Панель руководителя практики",
            reply_markup=get_practice_supervisor_panel_kb()
        )
    elif role == "admin_admin":
        await message.answer(
            "Панель админа",
            reply_markup=get_admin_panel_kb()
        )
    elif role == "admin_supervisor":
        await message.answer(
            "Панель суперадмина",
            reply_markup=get_superadmin_panel_kb()
        )
    else:
        await message.answer(
            "❌ Данная команда недоступна, так как ваша роль: user_unauthorized"
        )
