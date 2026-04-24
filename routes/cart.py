from flask import Blueprint, render_template, session, redirect, url_for, request
from urllib.parse import quote
import uuid
from model import get_product_by_id
from config import WHATSAPP_NUMBER, BUSINESS_NAME, WOMPI_PUBLIC_KEY

cart_bp = Blueprint("cart", __name__)


def get_cart_items():
    cart = session.get("cart", {})
    items = []
    total = 0
    for pid_str, qty in cart.items():
        product = get_product_by_id(int(pid_str))
        if product:
            subtotal = product["precio"] * qty
            items.append({**product, "cantidad": qty, "subtotal": subtotal})
            total += subtotal
    return items, total


@cart_bp.route("/carrito")
def carrito():
    items, total = get_cart_items()
    return render_template("cart.html", items=items, total=total)


@cart_bp.route("/agregar/<int:product_id>", methods=["POST"])
def agregar(product_id):
    cart = session.get("cart", {})
    key = str(product_id)
    try:
        qty = int(request.form.get("cantidad", 1))
        qty = max(1, min(qty, 50))
    except (ValueError, TypeError):
        qty = 1
    cart[key] = cart.get(key, 0) + qty
    session["cart"] = cart
    next_url = request.form.get("next") or request.referrer or url_for("main.index")
    return redirect(next_url)


@cart_bp.route("/quitar/<int:product_id>", methods=["POST"])
def quitar(product_id):
    cart = session.get("cart", {})
    key = str(product_id)
    if key in cart:
        if cart[key] > 1:
            cart[key] -= 1
        else:
            del cart[key]
    session["cart"] = cart
    return redirect(url_for("cart.carrito"))


@cart_bp.route("/eliminar/<int:product_id>", methods=["POST"])
def eliminar(product_id):
    cart = session.get("cart", {})
    cart.pop(str(product_id), None)
    session["cart"] = cart
    return redirect(url_for("cart.carrito"))


@cart_bp.route("/vaciar", methods=["POST"])
def vaciar():
    session.pop("cart", None)
    return redirect(url_for("cart.carrito"))


@cart_bp.route("/checkout-whatsapp")
def checkout_whatsapp():
    items, total = get_cart_items()
    if not items:
        return redirect(url_for("cart.carrito"))

    nombre = request.args.get("nombre", "")
    tel = request.args.get("tel", "")
    dir_ = request.args.get("dir", "")
    ciudad = request.args.get("ciudad", "")

    lineas = [f"¡Hola {BUSINESS_NAME}! Quiero hacer el siguiente pedido:\n"]
    for item in items:
        lineas.append(f"• {item['nombre']} x{item['cantidad']}kg — ${item['subtotal']:,}")
    lineas.append(f"\n*Total estimado: ${total:,}*")
    if nombre or dir_:
        lineas.append(f"\n📦 *Datos de entrega:*")
        if nombre: lineas.append(f"Nombre: {nombre}")
        if tel: lineas.append(f"Teléfono: {tel}")
        if dir_: lineas.append(f"Dirección: {dir_}")
        if ciudad: lineas.append(f"Ciudad/Barrio: {ciudad}")
    lineas.append("\nPor favor confirmar disponibilidad y precio final. ¡Gracias!")

    mensaje = "\n".join(lineas)
    url = f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(mensaje)}"
    return redirect(url)


@cart_bp.route("/checkout-tarjeta", methods=["POST"])
def checkout_tarjeta():
    items, total = get_cart_items()
    if not items:
        return redirect(url_for("cart.carrito"))
    referencia = f"APASTTO-{uuid.uuid4().hex[:8].upper()}"
    monto_centavos = total * 100
    return render_template("checkout_tarjeta.html",
                           items=items, total=total,
                           referencia=referencia,
                           monto_centavos=monto_centavos,
                           wompi_key=WOMPI_PUBLIC_KEY)
