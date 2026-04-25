from datetime import timedelta
from flask import Flask, session
from config import SECRET_KEY, DEBUG, BUSINESS_NAME, DATABASE_URL, WHATSAPP_NUMBER, WOMPI_PUBLIC_KEY
from database import db
from routes.main import main_bp
from routes.cart import cart_bp
from routes.admin import admin_bp

app = Flask(__name__, static_folder="static")

app.secret_key = SECRET_KEY
app.config.update(
    SQLALCHEMY_DATABASE_URI        = DATABASE_URL,
    SQLALCHEMY_TRACK_MODIFICATIONS = False,
    SESSION_COOKIE_HTTPONLY        = True,
    SESSION_COOKIE_SAMESITE        = "Lax",
    SESSION_COOKIE_SECURE          = not DEBUG,   # HTTPS en producción
    PERMANENT_SESSION_LIFETIME     = timedelta(hours=8),
)

db.init_app(app)

app.register_blueprint(main_bp)
app.register_blueprint(cart_bp)
app.register_blueprint(admin_bp)


@app.after_request
def security_headers(response):
    response.headers["X-Frame-Options"]        = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"]     = "geolocation=(), microphone=(), camera=()"
    return response


@app.context_processor
def inject_globals():
    cart = session.get("cart", {})
    return {
        "cart_count":     sum(cart.values()),
        "business_name":  BUSINESS_NAME,
        "whatsapp_number": WHATSAPP_NUMBER,
        "wompi_key":      WOMPI_PUBLIC_KEY,
    }


def _seed_db():
    from model import Product, SEED_PRODUCTS
    if Product.query.count() == 0:
        for d in SEED_PRODUCTS:
            db.session.add(Product(
                id=d["id"], nombre=d["nombre"], tipo=d["tipo"],
                categoria=d["categoria"], precio=d["precio"],
                precio_orig=d["precio"], descripcion=d["descripcion"],
                emoji=d["emoji"], imagen=d.get("imagen", ""),
            ))
        db.session.commit()


with app.app_context():
    db.create_all()
    try:
        from sqlalchemy import text, inspect as _inspect
        _cols = [c["name"] for c in _inspect(db.engine).get_columns("products")]
        if "stock" not in _cols:
            db.session.execute(text("ALTER TABLE products ADD COLUMN stock INTEGER"))
            db.session.commit()
    except Exception:
        pass
    _seed_db()


if __name__ == "__main__":
    app.run(debug=DEBUG)
