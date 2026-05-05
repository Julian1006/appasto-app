from flask import Blueprint, render_template, session, redirect, url_for, request, jsonify, flash
from urllib.parse import quote
import uuid, json
from model import get_product_by_id, get_combo_by_id, Order, Promo
from database import db
from config import WHATSAPP_NUMBER, BUSINESS_NAME, WOMPI_PUBLIC_KEY
from rewards import LOYALTY_DISCOUNT_PERCENT, LOYALTY_DAYS_VALID, maybe_generate_loyalty_coupon
from security import safe_redirect_target

cart_bp = Blueprint("cart", __name__)


def _clean_text(value, limit=120):
    return (value or "").strip()[:limit]


def _redirect_back(default_endpoint="main.index"):
    target = request.form.get("next") or request.referrer
    return redirect(safe_redirect_target(target, default_endpoint))

def _save_order(metodo, items, total, tel="", dir_="", ciudad="", referencia="", issue_reward=False):
    try:
        from model import Product as _Product
        reward_code = None
        items_data = []
        for i in items:
            entry = {"nombre": i["nombre"], "cantidad": i["cantidad"], "subtotal": i["subtotal"]}
            if i.get("is_combo"):
                entry["is_combo"] = True
                entry["combo_items"] = [{"id": ci["id"], "cantidad": ci["cantidad"]}
                                        for ci in i.get("items", []) if isinstance(ci.get("id"), int)]
            else:
                if isinstance(i.get("id"), int):
                    entry["id"] = i["id"]
            items_data.append(entry)
        order = Order(
            user_id=session.get("user_id"),
            metodo=metodo, total=total,
            items_json=json.dumps(items_data, ensure_ascii=False),
            tel=tel, direccion=dir_, ciudad=ciudad, referencia=referencia,
        )
        db.session.add(order)

        def _descontar(pid, qty):
            p = _Product.query.get(pid)
            if p and p.stock is not None:
                p.stock = max(0, p.stock - qty)
                if p.stock <= 0:
                    p.stock = 0
                    p.activo = False

        for item in items:
            if item.get("is_combo"):
                # Descontar stock de cada producto dentro del combo
                for prod in item.get("items", []):
                    if isinstance(prod.get("id"), int):
                        _descontar(prod["id"], prod["cantidad"] * item["cantidad"])
            else:
                pid = item.get("id")
                if isinstance(pid, int):
                    _descontar(pid, item["cantidad"])

        db.session.flush()
        if issue_reward:
            reward_code = maybe_generate_loyalty_coupon(order.user_id)
        db.session.commit()
        return reward_code
    except Exception:
        db.session.rollback()
        return None


def _cart_total(cart):
    total = 0
    for key, qty in cart.items():
        if key.startswith("combo_"):
            c = get_combo_by_id(int(key[6:]))
            if c and c["activo"] and c.get("vigente", True):
                total += c["precio"] * qty
        else:
            p = get_product_by_id(int(key))
            if p:
                total += p["precio"] * qty
    return total


def get_cart_items():
    cart = session.get("cart", {})
    cart_notes = session.get("cart_notes", {})
    items = []
    total = 0
    for key, qty in cart.items():
        if key.startswith("combo_"):
            cid = int(key[6:])
            combo = get_combo_by_id(cid)
            if combo and combo["activo"] and combo.get("vigente", True):
                subtotal = combo["precio"] * qty
                items.append({**combo, "cantidad": qty, "subtotal": subtotal,
                               "is_combo": True, "cart_key": key, "nota": "",
                               "url_minus":  url_for("cart.quitar_combo",  combo_id=cid),
                               "url_plus":   url_for("cart.agregar_combo", combo_id=cid),
                               "url_remove": url_for("cart.eliminar_combo", combo_id=cid)})
                total += subtotal
        else:
            pid = int(key)
            product = get_product_by_id(pid)
            if product:
                subtotal = product["precio"] * qty
                items.append({**product, "cantidad": qty, "subtotal": subtotal,
                               "is_combo": False, "cart_key": key,
                               "nota": cart_notes.get(key, ""),
                               "url_minus":  url_for("cart.quitar",   product_id=pid),
                               "url_plus":   url_for("cart.agregar",  product_id=pid),
                               "url_remove": url_for("cart.eliminar", product_id=pid),
                               "url_nota":   url_for("cart.actualizar_nota", product_id=pid)})
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


def _get_promo_info(total):
    """Returns (promo_dict, descuento) from session. Clears if invalid."""
    promo_data = session.get("promo")
    if not promo_data or total == 0:
        return None, 0
    p = Promo.query.get(promo_data.get("id"))
    if not p:
        session.pop("promo", None)
        return None, 0
    ok, _ = p.is_valid()
    if not ok:
        session.pop("promo", None)
        return None, 0
    descuento = p.calcular_descuento(total)
    return {"id": p.id, "codigo": p.codigo, "tipo": p.tipo, "valor": p.valor, "descuento": descuento}, descuento


def _aplicar_y_limpiar_promo(total):
    """Increments usage, clears session promo. Returns (descuento, codigo)."""
    promo_data = session.get("promo")
    if not promo_data:
        return 0, None
    p = Promo.query.get(promo_data.get("id"))
    if not p:
        session.pop("promo", None)
        return 0, None
    ok, _ = p.is_valid()
    if not ok:
        session.pop("promo", None)
        return 0, None
    descuento = p.calcular_descuento(total)
    p.veces_usado += 1
    db.session.commit()
    session.pop("promo", None)
    return descuento, p.codigo


@cart_bp.route("/carrito")
def carrito():
    items, total = get_cart_items()
    promo, descuento = _get_promo_info(total)
    total_final = total - descuento
    return render_template("cart.html", items=items, total=total,
                           promo=promo, descuento=descuento, total_final=total_final)


@cart_bp.route("/aplicar-promo", methods=["POST"])
def aplicar_promo():
    codigo = request.form.get("codigo", "").strip().upper()
    if not codigo:
        return redirect(url_for("cart.carrito"))
    p = Promo.query.filter_by(codigo=codigo).first()
    if not p:
        flash(f"❌ El cupón '{codigo}' no existe.", "error")
        return redirect(url_for("cart.carrito"))
    ok, msg = p.is_valid()
    if not ok:
        flash(f"❌ {msg}", "error")
        return redirect(url_for("cart.carrito"))
    items, total = get_cart_items()
    if not items:
        flash("El carrito está vacío.", "error")
        return redirect(url_for("cart.carrito"))
    descuento = p.calcular_descuento(total)
    session["promo"] = {"id": p.id, "codigo": p.codigo, "tipo": p.tipo, "valor": p.valor}
    flash(f"✅ Cupón '{p.codigo}' aplicado — ahorras ${descuento:,}", "success")
    return redirect(url_for("cart.carrito"))


@cart_bp.route("/quitar-promo", methods=["POST"])
def quitar_promo():
    session.pop("promo", None)
    return redirect(url_for("cart.carrito"))


@cart_bp.route("/agregar/<int:product_id>", methods=["POST"])
def agregar(product_id):
    from model import Product as _Product
    cart = session.get("cart", {})
    key = str(product_id)
    try:
        qty = int(request.form.get("cantidad", 1))
        qty = max(1, min(qty, 3))
    except (ValueError, TypeError):
        qty = 1

    # Limitar a las 3 presentaciones permitidas y al stock disponible
    current_in_cart = cart.get(key, 0)
    max_compra = 3
    p = _Product.query.get(product_id)
    qty = min(qty, max(0, max_compra - current_in_cart))
    if p and p.stock is not None:
        qty = min(qty, max(0, p.stock - current_in_cart))

    if qty <= 0:
        product = get_product_by_id(product_id)
        nombre = product["nombre"] if product else "Este producto"
        disponible = p.stock - current_in_cart if p and p.stock is not None else 0
        if current_in_cart >= max_compra:
            msg = f"⚠️ {nombre}: solo puedes comprar hasta 1.5 kg por pedido."
        elif disponible <= 0:
            msg = f"⚠️ {nombre}: stock agotado en el carrito."
        else:
            msg = f"⚠️ {nombre}: solo quedan {disponible} unidades (500 gr) disponibles."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            new_qty = current_in_cart
            subtotal = product["precio"] * new_qty if product else 0
            return jsonify({"ok": False, "count": sum(cart.values()),
                            "qty": new_qty, "subtotal": subtotal,
                            "total": _cart_total(cart), "msg": msg})
        flash(msg, "error")
        return _redirect_back("main.index")

    cart[key] = current_in_cart + qty
    session["cart"] = cart
    observacion = _clean_text(request.form.get("observacion", ""), 200)
    if observacion:
        cart_notes = session.get("cart_notes", {})
        cart_notes[key] = observacion
        session["cart_notes"] = cart_notes
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        product = get_product_by_id(product_id)
        new_qty = cart.get(key, 0)
        subtotal = product["precio"] * new_qty if product else 0
        return jsonify({"ok": True, "count": sum(cart.values()),
                        "qty": new_qty, "subtotal": subtotal, "total": _cart_total(cart)})
    return _redirect_back("main.index")


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
        return jsonify({"ok": True, "count": sum(cart.values()),
                        "qty": new_qty, "subtotal": subtotal,
                        "total": _cart_total(cart), "removed": new_qty == 0})
    return redirect(url_for("cart.carrito"))


@cart_bp.route("/eliminar/<int:product_id>", methods=["POST"])
def eliminar(product_id):
    cart = session.get("cart", {})
    cart.pop(str(product_id), None)
    session["cart"] = cart
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "count": sum(cart.values()),
                        "total": _cart_total(cart), "removed": True})
    return redirect(url_for("cart.carrito"))


@cart_bp.route("/nota/<int:product_id>", methods=["POST"])
def actualizar_nota(product_id):
    key = str(product_id)
    if key not in session.get("cart", {}):
        return redirect(url_for("cart.carrito"))
    observacion = _clean_text(request.form.get("observacion", ""), 200)
    cart_notes = session.get("cart_notes", {})
    if observacion:
        cart_notes[key] = observacion
    else:
        cart_notes.pop(key, None)
    session["cart_notes"] = cart_notes
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True})
    return redirect(url_for("cart.carrito"))


@cart_bp.route("/vaciar", methods=["POST"])
def vaciar():
    session.pop("cart", None)
    session.pop("cart_notes", None)
    return redirect(url_for("cart.carrito"))


def _merge_notas_from_form():
    """Lee notas del formulario y las guarda en sesión antes de get_cart_items()."""
    notas_form = {k[5:]: _clean_text(v, 200) for k, v in request.form.items() if k.startswith("nota_") and v.strip()}
    if notas_form:
        cn = session.get("cart_notes", {})
        cn.update(notas_form)
        session["cart_notes"] = cn


@cart_bp.route("/checkout-billetera", methods=["POST"])
def checkout_billetera():
    _merge_notas_from_form()
    items, total = get_cart_items()
    if not items:
        return redirect(url_for("cart.carrito"))
    metodo_raw = _clean_text(request.form.get("metodo", "Nequi"), 20).lower()
    metodo = "Daviplata" if metodo_raw == "daviplata" else "Nequi"
    tel   = _clean_text(request.form.get("tel", ""), 30)
    dir_  = _clean_text(request.form.get("dir", ""), 300)
    ciudad = _clean_text(request.form.get("ciudad", ""), 100)
    descuento, promo_cod = _aplicar_y_limpiar_promo(total)
    total_final = total - descuento
    lineas = [f"¡Hola {BUSINESS_NAME}! Quiero pagar con *{metodo}*:\n"]
    for item in items:
        lineas.append(f"• {item['nombre']} x{item['cantidad']} x 500 gr — ${item['subtotal']:,}")
        if item.get("nota"):
            lineas.append(f"   ↳ Indicaciones: {item['nota']}")
    if descuento:
        lineas.append(f"\n🏷️ Cupón {promo_cod}: -${descuento:,}")
        lineas.append(f"*Total: ${total_final:,}*")
    else:
        lineas.append(f"\n*Total: ${total:,}*")
    if tel or dir_:
        lineas.append(f"\n📦 *Datos de entrega:*")
        if tel:    lineas.append(f"Teléfono: {tel}")
        if dir_:   lineas.append(f"Dirección: {dir_}")
        if ciudad: lineas.append(f"Ciudad/Barrio: {ciudad}")
    lineas.append(f"\nPor favor indicarme el número {metodo} para realizar el pago y confirmar disponibilidad. ¡Gracias!")
    _save_order(metodo, items, total_final, tel=tel, dir_=dir_, ciudad=ciudad)
    wa_url = f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(chr(10).join(lineas))}"
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True})
    return redirect(wa_url)


@cart_bp.route("/checkout-efectivo", methods=["POST"])
def checkout_efectivo():
    _merge_notas_from_form()
    items, total = get_cart_items()
    if not items:
        return redirect(url_for("cart.carrito"))
    tel   = _clean_text(request.form.get("tel", ""), 30)
    dir_  = _clean_text(request.form.get("dir", ""), 300)
    ciudad = _clean_text(request.form.get("ciudad", ""), 100)
    descuento, promo_cod = _aplicar_y_limpiar_promo(total)
    total_final = total - descuento
    lineas = [f"¡Hola {BUSINESS_NAME}! Quiero pagar en *efectivo contra entrega*:\n"]
    for item in items:
        lineas.append(f"• {item['nombre']} x{item['cantidad']} x 500 gr — ${item['subtotal']:,}")
        if item.get("nota"):
            lineas.append(f"   ↳ Indicaciones: {item['nota']}")
    if descuento:
        lineas.append(f"\n🏷️ Cupón {promo_cod}: -${descuento:,}")
        lineas.append(f"*Total a pagar: ${total_final:,}*")
    else:
        lineas.append(f"\n*Total a pagar: ${total:,}*")
    if tel or dir_:
        lineas.append(f"\n📦 *Datos de entrega:*")
        if tel:    lineas.append(f"Teléfono: {tel}")
        if dir_:   lineas.append(f"Dirección: {dir_}")
        if ciudad: lineas.append(f"Ciudad/Barrio: {ciudad}")
    lineas.append("\nPor favor confirmar disponibilidad y coordinar la entrega. ¡Gracias!")
    _save_order("Efectivo", items, total_final, tel=tel, dir_=dir_, ciudad=ciudad)
    wa_url = f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(chr(10).join(lineas))}"
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True})
    return redirect(wa_url)


@cart_bp.route("/checkout-whatsapp", methods=["POST"])
def checkout_whatsapp():
    _merge_notas_from_form()
    items, total = get_cart_items()
    if not items:
        return redirect(url_for("cart.carrito"))

    nombre = _clean_text(request.form.get("nombre", ""), 120)
    tel = _clean_text(request.form.get("tel", ""), 30)
    dir_ = _clean_text(request.form.get("dir", ""), 300)
    ciudad = _clean_text(request.form.get("ciudad", ""), 100)

    descuento, promo_cod = _aplicar_y_limpiar_promo(total)
    total_final = total - descuento
    lineas = [f"¡Hola {BUSINESS_NAME}! Quiero hacer el siguiente pedido:\n"]
    for item in items:
        lineas.append(f"• {item['nombre']} x{item['cantidad']} x 500 gr — ${item['subtotal']:,}")
        if item.get("nota"):
            lineas.append(f"   ↳ Indicaciones: {item['nota']}")
    if descuento:
        lineas.append(f"\n🏷️ Cupón {promo_cod}: -${descuento:,}")
        lineas.append(f"*Total estimado: ${total_final:,}*")
    else:
        lineas.append(f"\n*Total estimado: ${total:,}*")
    if nombre or dir_:
        lineas.append(f"\n📦 *Datos de entrega:*")
        if nombre: lineas.append(f"Nombre: {nombre}")
        if tel: lineas.append(f"Teléfono: {tel}")
        if dir_: lineas.append(f"Dirección: {dir_}")
        if ciudad: lineas.append(f"Ciudad/Barrio: {ciudad}")
    lineas.append("\nPor favor confirmar disponibilidad y precio final. ¡Gracias!")
    _save_order("WhatsApp", items, total_final, tel=tel, dir_=dir_, ciudad=ciudad)
    mensaje = "\n".join(lineas)
    wa_url = f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(mensaje)}"
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True})
    return redirect(wa_url)


@cart_bp.route("/agregar-combo/<int:combo_id>", methods=["POST"])
def agregar_combo(combo_id):
    from model import Product as _Product
    combo = get_combo_by_id(combo_id)
    if not combo or not combo.get("activo") or not combo.get("vigente", True):
        return redirect(url_for("main.index"))
    cart = session.get("cart", {})
    key = f"combo_{combo_id}"
    try:
        qty = int(request.form.get("cantidad", 1))
        qty = max(1, min(qty, 20))
    except (ValueError, TypeError):
        qty = 1

    # Calcular máximo de combos permitido según stock de cada producto
    current_in_cart = cart.get(key, 0)
    max_permitido = 99
    for item in combo["items"]:
        p = _Product.query.get(item["id"])
        if p and p.stock is not None and item["cantidad"] > 0:
            max_por_este = p.stock // item["cantidad"]
            max_permitido = min(max_permitido, max_por_este)

    nuevo_total = min(current_in_cart + qty, max_permitido)
    if nuevo_total <= current_in_cart:
        msg = f"⚠️ {combo['nombre']}: no hay suficiente stock para agregar más unidades de este combo."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "msg": msg})
        flash(msg, "error")
        return _redirect_back("main.index")

    cart[key] = nuevo_total
    session["cart"] = cart
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        new_qty = cart.get(key, 0)
        subtotal = combo["precio"] * new_qty
        _, total = get_cart_items()
        return jsonify({"ok": True, "count": sum(cart.values()),
                        "qty": new_qty, "subtotal": subtotal, "total": total})
    return _redirect_back("main.index")


@cart_bp.route("/quitar-combo/<int:combo_id>", methods=["POST"])
def quitar_combo(combo_id):
    cart = session.get("cart", {})
    key = f"combo_{combo_id}"
    if key in cart:
        if cart[key] > 1:
            cart[key] -= 1
        else:
            del cart[key]
    session["cart"] = cart
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        combo = get_combo_by_id(combo_id)
        new_qty = cart.get(key, 0)
        subtotal = combo["precio"] * new_qty if combo and new_qty > 0 else 0
        return jsonify({"ok": True, "count": sum(cart.values()),
                        "qty": new_qty, "subtotal": subtotal,
                        "total": _cart_total(cart), "removed": new_qty == 0})
    return redirect(url_for("cart.carrito"))


@cart_bp.route("/eliminar-combo/<int:combo_id>", methods=["POST"])
def eliminar_combo(combo_id):
    cart = session.get("cart", {})
    cart.pop(f"combo_{combo_id}", None)
    session["cart"] = cart
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "count": sum(cart.values()),
                        "total": _cart_total(cart), "removed": True})
    return redirect(url_for("cart.carrito"))


@cart_bp.route("/checkout-tarjeta", methods=["POST"])
def checkout_tarjeta():
    _merge_notas_from_form()
    items, total = get_cart_items()
    if not items:
        return redirect(url_for("cart.carrito"))
    tel = _clean_text(request.form.get("tel", ""), 30)
    dir_ = _clean_text(request.form.get("dir", ""), 300)
    ciudad = _clean_text(request.form.get("ciudad", ""), 100)
    descuento, promo_cod = _aplicar_y_limpiar_promo(total)
    total_final = total - descuento
    referencia = f"APASTTO-{uuid.uuid4().hex[:8].upper()}"
    monto_centavos = total_final * 100
    _save_order("Tarjeta", items, total_final, tel=tel, dir_=dir_, ciudad=ciudad, referencia=referencia)
    session.pop("cart", None)
    return render_template("checkout_tarjeta.html",
                           items=items, total=total_final,
                           referencia=referencia,
                           monto_centavos=monto_centavos,
                           wompi_key=WOMPI_PUBLIC_KEY)
