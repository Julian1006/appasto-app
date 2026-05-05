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
from config import SECRET_KEY, DEBUG, IS_PRODUCTION, BUSINESS_NAME, DATABASE_URL, WHATSAPP_NUMBER, WOMPI_PUBLIC_KEY
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
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
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


with app.app_context():
    db.create_all()  # Crea todas las tablas definidas en model.py si no existen
    try:
        # Migraciones manuales para columnas agregadas después del deploy inicial
        # db.create_all() no altera tablas existentes, por eso usamos ALTER TABLE
        from sqlalchemy import text, inspect as _inspect
        _cols = [c["name"] for c in _inspect(db.engine).get_columns("products")]
        if "stock" not in _cols:
            db.session.execute(text("ALTER TABLE products ADD COLUMN stock INTEGER"))
            db.session.commit()
        if "destacado" not in _cols:
            db.session.execute(text("ALTER TABLE products ADD COLUMN destacado INTEGER NOT NULL DEFAULT 0"))
            _ids = ",".join(str(i) for i in [4, 5, 6, 1, 3, 29, 31, 49, 60, 73, 87, 8])
            db.session.execute(text(f"UPDATE products SET destacado=1 WHERE id IN ({_ids})"))
            db.session.commit()
        if "orden_destacado" not in _cols:
            db.session.execute(text("ALTER TABLE products ADD COLUMN orden_destacado INTEGER DEFAULT 0"))
            db.session.commit()
        if "badge" not in _cols:
            db.session.execute(text("ALTER TABLE products ADD COLUMN badge VARCHAR(20) DEFAULT ''"))
            db.session.commit()
        _combo_cols = [c["name"] for c in _inspect(db.engine).get_columns("combos")]
        if "fecha_inicio" not in _combo_cols:
            db.session.execute(text("ALTER TABLE combos ADD COLUMN fecha_inicio DATE"))
            db.session.commit()
        if "fecha_fin" not in _combo_cols:
            db.session.execute(text("ALTER TABLE combos ADD COLUMN fecha_fin DATE"))
            db.session.commit()
        _order_cols = [c["name"] for c in _inspect(db.engine).get_columns("orders")]
        if "user_id" not in _order_cols:
            db.session.execute(text("ALTER TABLE orders ADD COLUMN user_id INTEGER"))
            db.session.commit()
        if "reward_code" not in _order_cols:
            db.session.execute(text("ALTER TABLE orders ADD COLUMN reward_code VARCHAR(50)"))
            db.session.commit()
        _promo_cols = [c["name"] for c in _inspect(db.engine).get_columns("promos")]
        if "visible_cliente" not in _promo_cols:
            db.session.execute(text("ALTER TABLE promos ADD COLUMN visible_cliente INTEGER NOT NULL DEFAULT 0"))
            db.session.commit()
        _user_cols = [c["name"] for c in _inspect(db.engine).get_columns("users")]
        if "reward_200k_issued" not in _user_cols:
            db.session.execute(text("ALTER TABLE users ADD COLUMN reward_200k_issued INTEGER NOT NULL DEFAULT 0"))
            db.session.commit()
        if "reward_200k_code" not in _user_cols:
            db.session.execute(text("ALTER TABLE users ADD COLUMN reward_200k_code VARCHAR(50)"))
            db.session.commit()
        if "ultimo_reward_at" not in _user_cols:
            db.session.execute(text("ALTER TABLE users ADD COLUMN ultimo_reward_at DATETIME"))
            db.session.commit()
    except Exception:
        pass
    _seed_db()
    _seed_categorias()


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
