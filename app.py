# =============================================================================
# app.py — Punto de entrada principal de la aplicación Flask "Apastto"
#
# ARQUITECTURA:
#   - Flask + SQLAlchemy (ORM) con SQLite en local y PostgreSQL en producción
#   - 3 Blueprints: main_bp (tienda), cart_bp (carrito), admin_bp (panel admin)
#   - Base de datos gestionada por db en database.py (instancia SQLAlchemy)
#   - Configuración sensible (contraseñas, llaves) en variables de entorno via config.py
#
# MODELOS (model.py):
#   - Product: productos del catálogo (stock, precio, imagen, activo/inactivo)
#   - Order: pedidos guardados al hacer checkout
#   - Combo: combos de productos (descuenta stock de cada producto incluido)
#   - Promo: cupones de descuento (porcentaje o monto fijo, con límite de usos)
#
# SESIÓN (Flask session):
#   - session["cart"]: dict {"<product_id>": qty, "combo_<combo_id>": qty}
#   - session["admin"]: True cuando el admin está logueado
#   - session["promo"]: dict {id, codigo, tipo, valor} cuando hay cupón activo
#
# FLUJO DE COMPRA:
#   1. Cliente agrega productos/combos al carrito (rutas /agregar/, /agregar-combo/)
#   2. Va al carrito (/carrito), opcionalmente aplica cupón (/aplicar-promo)
#   3. Completa datos de entrega y elige método de pago
#   4. Checkout genera URL de WhatsApp con el pedido pre-escrito y guarda Order en DB
#   5. Admin ve el pedido en /admin y cambia el estado (pendiente→completado/cancelado)
#      Al cancelar, el stock se restaura automáticamente
#
# PAGOS SOPORTADOS:
#   - WhatsApp directo (checkout-whatsapp)
#   - Billetera digital: Nequi / Daviplata (checkout-billetera)
#   - Efectivo contra entrega (checkout-efectivo)
#   - Tarjeta / PSE via Wompi (checkout-tarjeta) — requiere WOMPI_PUBLIC_KEY en .env
#
# VARIABLES DE ENTORNO (.env en local, vars en Render en producción):
#   DATABASE_URL    → PostgreSQL en prod, SQLite si no está definida
#   SECRET_KEY      → Llave secreta de Flask (sessions)
#   ADMIN_PASSWORD  → Contraseña del panel admin
#   WHATSAPP_NUMBER → Número de WhatsApp del negocio (con código de país, sin +)
#   WOMPI_PUBLIC_KEY → Llave pública de Wompi para pagos con tarjeta
#
# IMÁGENES DE PRODUCTOS:
#   - Se guardan en static/images/ con nombre aleatorio (prod_<uuid>.ext)
#   - Se referencian en la DB como "images/prod_xxx.jpg"
#   - Al mostrar en template: url_for('static', filename=producto.imagen)
# =============================================================================

from datetime import timedelta
from flask import Flask, session
from werkzeug.middleware.proxy_fix import ProxyFix
from config import (SECRET_KEY, DEBUG, IS_PRODUCTION, BUSINESS_NAME, DATABASE_URL,
                    WHATSAPP_NUMBER, WOMPI_PUBLIC_KEY, DELIVERY_RADIUS_KM,
                    DELIVERY_ORIGIN_LAT, DELIVERY_ORIGIN_LNG)
from database import db
from routes.main import main_bp
from routes.cart import cart_bp
from routes.admin import admin_bp
from routes.auth import auth_bp
from security import apply_security_headers, csrf_field, csrf_token, register_security

app = Flask(__name__, static_folder="static")
if IS_PRODUCTION:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

app.secret_key = SECRET_KEY
app.config.update(
    SQLALCHEMY_DATABASE_URI        = DATABASE_URL,
    SQLALCHEMY_TRACK_MODIFICATIONS = False,
    PREFERRED_URL_SCHEME           = "https" if IS_PRODUCTION else "http",
    SESSION_COOKIE_HTTPONLY        = True,
    SESSION_COOKIE_SAMESITE        = "Lax",
    SESSION_COOKIE_SECURE          = IS_PRODUCTION,
    PERMANENT_SESSION_LIFETIME     = timedelta(hours=8),
    MAX_CONTENT_LENGTH             = 8 * 1024 * 1024,  # 8 MB máx por imagen subida
)
app.config.update(
    SESSION_COOKIE_NAME          = "__Host-apastto-session" if IS_PRODUCTION else "apastto_session",
    SESSION_COOKIE_PATH          = "/",
    SESSION_REFRESH_EACH_REQUEST = True,
)

# Postgres cierra las conexiones inactivas (mantenimiento de Render, reinicio por
# cambio de plan) y SQLAlchemy se queda con sockets muertos en el pool: la siguiente
# peticion que los reutiliza revienta con "SSL connection has been closed unexpectedly".
# pre_ping prueba la conexion antes de entregarla y abre otra si esta muerta.
# Solo aplica a Postgres; en SQLite local estas opciones no tienen sentido.
if DATABASE_URL.startswith("postgresql"):
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,     # recicla conexiones antes de que la red las corte
        "pool_size": 5,
        "max_overflow": 5,       # 2 workers x 10 = 20 conexiones maximo, limite del plan es 100
        "connect_args": {
            "connect_timeout": 10,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
        },
    }

db.init_app(app)
register_security(app)

app.register_blueprint(main_bp)
app.register_blueprint(cart_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(auth_bp)


@app.after_request
def security_headers(response):
    # Headers de seguridad básicos para producción
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(self), microphone=(), camera=()")
    return response


@app.after_request
def advanced_security_headers(response):
    return apply_security_headers(response, is_production=IS_PRODUCTION)


@app.context_processor
def inject_globals():
    # Variables disponibles en TODOS los templates automáticamente
    cart = session.get("cart", {})
    current_user = None
    if session.get("user_id"):
        from model import User
        current_user = User.query.get(session["user_id"])
    return {
        "cart_count":      sum(cart.values()),   # Número total de items en carrito (para badge navbar)
        "business_name":   "Apastto",
        "whatsapp_number": WHATSAPP_NUMBER,
        "wompi_key":       WOMPI_PUBLIC_KEY,
        "current_user":    current_user,
        "delivery_radius_km": DELIVERY_RADIUS_KM,
        "delivery_origin_lat": DELIVERY_ORIGIN_LAT,
        "delivery_origin_lng": DELIVERY_ORIGIN_LNG,
        "csrf_token":      csrf_token,
        "csrf_field":      csrf_field,
    }


_DESTACADOS_DEFAULT = {4, 5, 6, 1, 3, 29, 31, 49, 60, 73, 87, 8}  # IDs de productos destacados por defecto

def _seed_db():
    # Carga los productos iniciales (seed) solo si la tabla está vacía
    # Los productos están definidos en model.py → SEED_PRODUCTS
    from model import Product, SEED_PRODUCTS
    if Product.query.count() == 0:
        for d in SEED_PRODUCTS:
            db.session.add(Product(
                id=d["id"], nombre=d["nombre"], tipo=d["tipo"],
                categoria=d["categoria"], precio=d["precio"],
                precio_orig=d["precio"], descripcion=d["descripcion"],
                emoji=d["emoji"], imagen=d.get("imagen", ""),
                destacado=d["id"] in _DESTACADOS_DEFAULT,
            ))
        db.session.commit()


def _seed_categorias():
    from model import Categoria, SEED_CATEGORIAS
    if Categoria.query.count() == 0:
        for d in SEED_CATEGORIAS:
            db.session.add(Categoria(**d))
        db.session.commit()


def _safe_exec(sql):
    # Ejecuta una sentencia suelta y hace rollback si falla.
    # El rollback es imprescindible en PostgreSQL: ahí un error deja la
    # transacción abortada y TODA consulta posterior falla hasta revertirla
    # (en SQLite no pasa, por eso el bug solo aparecía en producción).
    # Además, con varios workers arrancando a la vez, es normal que un
    # ALTER TABLE falle porque otro worker ya lo aplicó.
    from sqlalchemy import text
    try:
        db.session.execute(text(sql))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _columnas(tabla):
    from sqlalchemy import inspect as _inspect
    try:
        return [c["name"] for c in _inspect(db.engine).get_columns(tabla)]
    except Exception:
        db.session.rollback()
        return []


with app.app_context():
    db.create_all()  # Crea todas las tablas definidas en model.py si no existen

    # Migraciones manuales para columnas agregadas después del deploy inicial
    # db.create_all() no altera tablas existentes, por eso usamos ALTER TABLE
    _cols = _columnas("products")
    if "stock" not in _cols:
        _safe_exec("ALTER TABLE products ADD COLUMN stock INTEGER")
    if "destacado" not in _cols:
        _safe_exec("ALTER TABLE products ADD COLUMN destacado INTEGER NOT NULL DEFAULT 0")
        _ids = ",".join(str(i) for i in sorted(_DESTACADOS_DEFAULT))
        _safe_exec(f"UPDATE products SET destacado=1 WHERE id IN ({_ids})")
    if "orden_destacado" not in _cols:
        _safe_exec("ALTER TABLE products ADD COLUMN orden_destacado INTEGER DEFAULT 0")
    if "badge" not in _cols:
        _safe_exec("ALTER TABLE products ADD COLUMN badge VARCHAR(20) DEFAULT ''")

    _combo_cols = _columnas("combos")
    if "imagen" not in _combo_cols:
        _safe_exec("ALTER TABLE combos ADD COLUMN imagen VARCHAR(300) DEFAULT ''")
    if "fecha_inicio" not in _combo_cols:
        _safe_exec("ALTER TABLE combos ADD COLUMN fecha_inicio DATE")
    if "fecha_fin" not in _combo_cols:
        _safe_exec("ALTER TABLE combos ADD COLUMN fecha_fin DATE")

    _order_cols = _columnas("orders")
    if "user_id" not in _order_cols:
        _safe_exec("ALTER TABLE orders ADD COLUMN user_id INTEGER")
    if "reward_code" not in _order_cols:
        _safe_exec("ALTER TABLE orders ADD COLUMN reward_code VARCHAR(50)")

    _promo_cols = _columnas("promos")
    if "visible_cliente" not in _promo_cols:
        _safe_exec("ALTER TABLE promos ADD COLUMN visible_cliente INTEGER NOT NULL DEFAULT 0")

    _user_cols = _columnas("users")
    if "reward_200k_issued" not in _user_cols:
        _safe_exec("ALTER TABLE users ADD COLUMN reward_200k_issued INTEGER NOT NULL DEFAULT 0")
    if "reward_200k_code" not in _user_cols:
        _safe_exec("ALTER TABLE users ADD COLUMN reward_200k_code VARCHAR(50)")
    if "ultimo_reward_at" not in _user_cols:
        _safe_exec("ALTER TABLE users ADD COLUMN ultimo_reward_at TIMESTAMP")

    # El seed no debe tumbar el arranque: si falla, el sitio sigue en pie
    try:
        _seed_db()
        _seed_categorias()
    except Exception:
        db.session.rollback()

    _safe_exec("UPDATE categorias SET activo=0 WHERE nombre='Molidas'")


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
