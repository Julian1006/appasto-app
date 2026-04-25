from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify
from urllib.parse import quote
import uuid, json
from model import get_product_by_id, Order
from database import db
from config import WHATSAPP_NUMBER, BUSINESS_NAME, WOMPI_PUBLIC_KEY

cart_bp = Blueprint("cart", __name__)


def _save_order(metodo, items, total, tel="", dir_="", ciudad="", referencia=""):
    try:
        from model import Product as _Product
        items_data = [{"nombre": i["nombre"], "cantidad": i["cantidad"], "subtotal": i["subtotal"]} for i in items]
        order = Order(
            metodo=metodo, total=total,
            items_json=json.dumps(items_data, ensure_ascii=False),
            tel=tel, direccion=dir_, ciudad=ciudad, referencia=referencia,
        )
        db.session.add(order)
        # Descontar stock y desactivar si llega a 0
        for item in items:
            p = _Product.query.get(item["id"])
            if p and p.stock is not None:
                p.stock = max(0, p.stock - item["cantidad"])
                if p.stock <= 0:
                    p.stock = 0
                    p.activo = False
        db.session.commit()
    except Exception:
        db.session.rollback()


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


@cart_bp.route("/api/cart")
def api_cart():
    items, total = get_cart_items()
    return jsonify({
        "items": [{"id": it["id"], "nombre": it["nombre"], "emoji": it["emoji"],
                   "precio": it["precio"], "qty": it["cantidad"], "subtotal": it["subtotal"]}
                  for it in items],
        "total": total,
        "count": sum(session.get("cart", {}).values()),
    })


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
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        product = get_product_by_id(product_id)
        new_qty = cart.get(key, 0)
        subtotal = product["precio"] * new_qty if product else 0
        _, total = get_cart_items()
        return jsonify({"ok": True, "count": sum(cart.values()),
                        "qty": new_qty, "subtotal": subtotal, "total": total})
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
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        product = get_product_by_id(product_id)
        new_qty = cart.get(key, 0)
        subtotal = product["precio"] * new_qty if product and new_qty > 0 else 0
        _, total = get_cart_items()
        return jsonify({"ok": True, "count": sum(cart.values()),
                        "qty": new_qty, "subtotal": subtotal, "total": total,
                        "removed": new_qty == 0})
    return redirect(url_for("cart.carrito"))


@cart_bp.route("/eliminar/<int:product_id>", methods=["POST"])
def eliminar(product_id):
    cart = session.get("cart", {})
    cart.pop(str(product_id), None)
    session["cart"] = cart
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        _, total = get_cart_items()
        return jsonify({"ok": True, "count": sum(cart.values()),
                        "total": total, "removed": True})
    return redirect(url_for("cart.carrito"))


@cart_bp.route("/vaciar", methods=["POST"])
def vaciar():
    session.pop("cart", None)
    return redirect(url_for("cart.carrito"))


@cart_bp.route("/checkout-billetera")
def checkout_billetera():
    items, total = get_cart_items()
    if not items:
        return redirect(url_for("cart.carrito"))
    metodo = request.args.get("metodo", "Nequi").capitalize()
    tel   = request.args.get("tel", "")
    dir_  = request.args.get("dir", "")
    ciudad = request.args.get("ciudad", "")
    lineas = [f"¡Hola {BUSINESS_NAME}! Quiero pagar con *{metodo}*:\n"]
    for item in items:
        lineas.append(f"• {item['nombre']} x{item['cantidad']}lb — ${item['subtotal']:,}")
    lineas.append(f"\n*Total: ${total:,}*")
    if tel or dir_:
        lineas.append(f"\n📦 *Datos de entrega:*")
        if tel:    lineas.append(f"Teléfono: {tel}")
        if dir_:   lineas.append(f"Dirección: {dir_}")
        if ciudad: lineas.append(f"Ciudad/Barrio: {ciudad}")
    lineas.append(f"\nPor favor indicarme el número {metodo} para realizar el pago y confirmar disponibilidad. ¡Gracias!")
    _save_order(metodo, items, total, tel=tel, dir_=dir_, ciudad=ciudad)
    url = f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(chr(10).join(lineas))}"
    return redirect(url)


@cart_bp.route("/checkout-efectivo")
def checkout_efectivo():
    items, total = get_cart_items()
    if not items:
        return redirect(url_for("cart.carrito"))
    tel   = request.args.get("tel", "")
    dir_  = request.args.get("dir", "")
    ciudad = request.args.get("ciudad", "")
    lineas = [f"¡Hola {BUSINESS_NAME}! Quiero pagar en *efectivo contra entrega*:\n"]
    for item in items:
        lineas.append(f"• {item['nombre']} x{item['cantidad']}lb — ${item['subtotal']:,}")
    lineas.append(f"\n*Total a pagar: ${total:,}*")
    if tel or dir_:
        lineas.append(f"\n📦 *Datos de entrega:*")
        if tel:    lineas.append(f"Teléfono: {tel}")
        if dir_:   lineas.append(f"Dirección: {dir_}")
        if ciudad: lineas.append(f"Ciudad/Barrio: {ciudad}")
    lineas.append("\nPor favor confirmar disponibilidad y coordinar la entrega. ¡Gracias!")
    _save_order("Efectivo", items, total, tel=tel, dir_=dir_, ciudad=ciudad)
    url = f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(chr(10).join(lineas))}"
    return redirect(url)


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
    _save_order("WhatsApp", items, total, tel=tel, dir_=dir_, ciudad=ciudad)
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
    _save_order("Tarjeta", items, total, referencia=referencia)
    return render_template("checkout_tarjeta.html",
                           items=items, total=total,
                           referencia=referencia,
                           monto_centavos=monto_centavos,
                           wompi_key=WOMPI_PUBLIC_KEY)
