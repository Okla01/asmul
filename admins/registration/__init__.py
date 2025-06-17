from .handlers import router as admin_registration_router

def setup_admin_registration(dp):
    dp.include_router(admin_registration_router)
