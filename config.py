import os
import secrets as _secrets
import hashlib

BUSINESS_NAME   = "Apastto"
WHATSAPP_NUMBER = "573202055525"
WOMPI_PUBLIC_KEY = os.environ.get("WOMPI_PUBLIC_KEY", "pub_test_XXXXXXXX")

# Cobertura de domicilios: origen en Cl. 170 #20a-64, Usaquen, Bogota.
DELIVERY_RADIUS_KM = float(os.environ.get("DELIVERY_RADIUS_KM", "15"))
DELIVERY_ORIGIN_LAT = float(os.environ.get("DELIVERY_ORIGIN_LAT", "4.7538"))
DELIVERY_ORIGIN_LNG = float(os.environ.get("DELIVERY_ORIGIN_LNG", "-74.0460"))

_db_url = os.environ.get("DATABASE_URL", "sqlite:///apastto.db")
DATABASE_URL = _db_url.replace("postgres://", "postgresql://", 1) if _db_url.startswith("postgres://") else _db_url

DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
IS_PRODUCTION = (
    os.environ.get("APP_ENV", "").lower() == "production"
    or os.environ.get("FLASK_ENV", "").lower() == "production"
    or os.environ.get("RENDER", "").lower() == "true"
    or (_db_url.startswith(("postgres://", "postgresql://")) and not DEBUG)
)

# En produccion es mejor configurar SECRET_KEY y ADMIN_PASSWORD_HASH o ADMIN_PASSWORD.
# Si no existen, usamos fallbacks para que Render pueda arrancar sin edicion manual.
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if IS_PRODUCTION:
        seed = "|".join([
            BUSINESS_NAME,
            DATABASE_URL,
            WOMPI_PUBLIC_KEY,
            os.environ.get("RENDER_SERVICE_ID", ""),
            os.environ.get("RENDER_EXTERNAL_HOSTNAME", ""),
        ])
        SECRET_KEY = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    else:
        SECRET_KEY = _secrets.token_hex(32)

ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()
if not (ADMIN_PASSWORD_HASH or ADMIN_PASSWORD):
    ADMIN_PASSWORD = "Apastto@2024"
