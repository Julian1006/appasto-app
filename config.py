import os

BUSINESS_NAME = "Appasto"
WHATSAPP_NUMBER = "573202055525"
SECRET_KEY = "appasto-secret-key-2024"
DEBUG = True
WOMPI_PUBLIC_KEY = "pub_test_XXXXXXXX"
ADMIN_PASSWORD = "Appasto@2024"

_db_url = os.environ.get("DATABASE_URL", "sqlite:///appasto.db")
# Render usa postgres://, SQLAlchemy necesita postgresql://
DATABASE_URL = _db_url.replace("postgres://", "postgresql://", 1) if _db_url.startswith("postgres://") else _db_url
