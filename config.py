import os, secrets as _secrets

BUSINESS_NAME   = "Appasto"
WHATSAPP_NUMBER = "573202055525"
WOMPI_PUBLIC_KEY = os.environ.get("WOMPI_PUBLIC_KEY", "pub_test_XXXXXXXX")

# En Render: configura SECRET_KEY y ADMIN_PASSWORD como variables de entorno
SECRET_KEY     = os.environ.get("SECRET_KEY") or _secrets.token_hex(32)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Appasto@2024")
DEBUG          = os.environ.get("FLASK_DEBUG", "0") == "1"

_db_url = os.environ.get("DATABASE_URL", "sqlite:///appasto.db")
DATABASE_URL = _db_url.replace("postgres://", "postgresql://", 1) if _db_url.startswith("postgres://") else _db_url
