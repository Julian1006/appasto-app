from flask import Flask
from config import SECRET_KEY, DEBUG, BUSINESS_NAME
from routes.main import main_bp
from routes.cart import cart_bp

app = Flask(__name__, static_folder="static")
app.secret_key = SECRET_KEY

app.register_blueprint(main_bp)
app.register_blueprint(cart_bp)


@app.context_processor
def inject_globals():
    from flask import session
    cart = session.get("cart", {})
    cart_count = sum(cart.values())
    from config import WHATSAPP_NUMBER, WOMPI_PUBLIC_KEY
    return {"cart_count": cart_count, "business_name": BUSINESS_NAME,
            "whatsapp_number": WHATSAPP_NUMBER, "wompi_key": WOMPI_PUBLIC_KEY}


if __name__ == "__main__":
    app.run(debug=DEBUG)
