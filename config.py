import os
import secrets as _secrets

BUSINESS_NAME   = "Appasto"
WHATSAPP_NUMBER = "573202055525"
WOMPI_PUBLIC_KEY = os.environ.get("WOMPI_PUBLIC_KEY", "pub_test_XXXXXXXX")

_db_url = os.environ.get("DATABASE_URL", "sqlite:///appasto.db")
DATABASE_URL = _db_url.replace("postgres://", "postgresql://", 1) if _db_url.startswith("postgres://") else _db_url

DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
IS_PRODUCTION = (
    os.environ.get("APP_ENV", "").lower() == "production"
    or os.environ.get("FLASK_ENV", "").lower() == "production"
    or os.environ.get("RENDER", "").lower() == "true"
    or (_db_url.startswith(("postgres://", "postgresql://")) and not DEBUG)
)

# En produccion configura SECRET_KEY y ADMIN_PASSWORD_HASH o ADMIN_PASSWORD.
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise RuntimeError("SECRET_KEY es obligatorio en produccion.")
    SECRET_KEY = _secrets.token_hex(32)

ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()
if IS_PRODUCTION and not (ADMIN_PASSWORD_HASH or ADMIN_PASSWORD):
    raise RuntimeError("ADMIN_PASSWORD_HASH o ADMIN_PASSWORD es obligatorio en produccion.")
if not (ADMIN_PASSWORD_HASH or ADMIN_PASSWORD):
    ADMIN_PASSWORD = "Appasto@2024"
if IS_PRODUCTION and ADMIN_PASSWORD == "Appasto@2024":
    raise RuntimeError("Cambia ADMIN_PASSWORD antes de desplegar en produccion.")
