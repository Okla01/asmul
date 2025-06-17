import asyncio
import logging

from admins.superadmin.mailing.scheduler import mailing_scheduler
from user.auth.handlers import *
from user.registration.handlers import *

from admins.superadmin.utils.import_excel import import_excel_users, EXCEL_PATH
from admins.superadmin.manage_user.handlers import *
from admins.superadmin.view_cand.handlers import *
from admins.superadmin.faq.handlers import *
from admins.superadmin.feedback_settings.handlers import *
from admins.superadmin.mailing.handlers import *
from admins.superadmin.events.handlers import *
from admins.superadmin.violations.handlers import *
from admins.superadmin.reports.handlers import *

from admins.practice_supervisor.handlers import *
from admins.practice_supervisor.registration.handlers import *
from admins.admin.handlers import *
from admins.handlers import *

from admins.registration import setup_admin_registration
from db.init_db import init_db
from admins.role_commands import router as role_router

async def on_startup(bot: Bot) -> None:
    """
    Вызывается автоматически при старте Dispatcher'а.
    Запускаем планировщик рассылок в отдельной задаче
    **(без await, чтобы не блокировать запуск бота).**
    """
    asyncio.create_task(mailing_scheduler(bot))


# Инициализируем базу данных
init_db()


# Регистрация всех роутеров
setup_admin_registration(dp)
dp.include_router(role_router)

dp.startup.register(on_startup)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s"
)


async def main() -> None:
    # import_excel_users()
    logging.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
