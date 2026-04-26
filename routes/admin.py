import json
import os
import uuid
from datetime import date, datetime, timedelta
from functools import wraps
from hmac import compare_digest
from time import time
from collections import defaultdict
from flask import Blueprint, render_template, request, redirect, url_for, session, abort
from werkzeug.utils import secure_filename
from config import ADMIN_PASSWORD
from database import db
from model import Product, Order, Combo, Promo
from rewards import (LOYALTY_DISCOUNT_PERCENT, LOYALTY_DAYS_VALID, LOYALTY_THRESHOLD,
                     LOYALTY_REPEAT_COP, LOYALTY_REPEAT_ORDERS, LOYALTY_COOLDOWN_DAYS,
                     maybe_generate_loyalty_coupon, remove_loyalty_coupon_for_order)

_UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "images")
_ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}

def _save_image(file):
    if not file or not file.filename:
        return ""
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in _ALLOWED_EXT:
        return ""
    os.makedirs(_UPLOAD_FOLDER, exist_ok=True)
    filename = f"prod_{uuid.uuid4().hex[:10]}.{ext}"
    file.save(os.path.join(_UPLOAD_FOLDER, filename))
    return f"images/{filename}"

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# Rate limiting en memoria: máx 5 intentos fallidos por IP, bloqueo 15 min
_failed = defaultdict(list)
_MAX_ATTEMPTS = 5
_LOCKOUT_SECS = 900


def _parse_date_field(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()


def _is_locked(ip):
    now = time()
    _failed[ip] = [t for t in _failed[ip] if now - t < _LOCKOUT_SECS]
    return len(_failed[ip]) >= _MAX_ATTEMPTS


def _record_fail(ip):
    _failed[ip].append(time())


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/activar", methods=["POST"])
def activar():
    """Activa la sesión de admin desde la página de cuenta del cliente."""
    ip = _ip()
    if _is_locked(ip):
        flash("Demasiados intentos fallidos. Espera 15 minutos.", "error")
        return redirect(request.referrer or url_for("auth.account"))
    pwd = request.form.get("password", "")
    if compare_digest(pwd, ADMIN_PASSWORD):
        session.permanent = True
        session["admin"] = True
        _failed.pop(ip, None)
        return redirect(url_for("admin.dashboard"))
    _record_fail(ip)
    flash("Código incorrecto.", "error")
    return redirect(request.referrer or url_for("auth.account"))


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    ip = _ip()
    error = None
    locked = _is_locked(ip)

    if request.method == "POST":
        if locked:
            error = "Demasiados intentos fallidos. Espera 15 minutos."
        else:
            pwd = request.form.get("password", "")
            if compare_digest(pwd, ADMIN_PASSWORD):
                session.permanent = True
                session["admin"] = True
                _failed.pop(ip, None)
                return redirect(url_for("admin.dashboard"))
            _record_fail(ip)
            remaining = _MAX_ATTEMPTS - len(_failed[ip])
            error = f"Contraseña incorrecta. Intentos restantes: {max(0, remaining)}."

    return render_template("admin_login.html", error=error, locked=locked)


@admin_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("admin.login"))


@admin_bp.route("/")
@admin_required
def dashboard():
    _cleanup_old_orders()
    productos = Product.query.order_by(Product.id).all()
    pedidos   = Order.query.order_by(Order.fecha.desc()).all()
    ahora = datetime.utcnow()
    deletable_ids = {o.id for o in pedidos if ahora - o.fecha >= timedelta(hours=24)}
    combos    = Combo.query.order_by(Combo.id.desc()).all()
    promos    = Promo.query.order_by(Promo.id.desc()).all()
    n_dest    = Product.query.filter_by(destacado=True).count()
    prod_map  = {p.id: p for p in productos}
    today     = date.today()
    combos_vigentes = sum(1 for c in combos if c.activo and c.esta_vigente(today))
    combos_programados = sum(1 for c in combos if c.estado_vigencia(today) == "programado")
    combos_vencidos = sum(1 for c in combos if c.estado_vigencia(today) == "vencido")

    # IDs de combos con algún producto sin stock suficiente
    combos_sin_stock = set()
    for c in combos:
        for item in c.items:
            p = prod_map.get(item["id"])
            if not p or not p.activo or (p.stock is not None and p.stock < item["cantidad"]):
                combos_sin_stock.add(c.id)
                break

    return render_template("admin.html", productos=productos, pedidos=pedidos,
                           combos=combos, combos_sin_stock=combos_sin_stock,
                           promos=promos, n_dest=n_dest, max_dest=MAX_DESTACADOS,
                           combos_vigentes=combos_vigentes,
                           combos_programados=combos_programados,
                           combos_vencidos=combos_vencidos,
                           deletable_ids=deletable_ids,
                           loyalty_percent=LOYALTY_DISCOUNT_PERCENT,
                           loyalty_days=LOYALTY_DAYS_VALID,
                           loyalty_repeat_cop=LOYALTY_REPEAT_COP,
                           loyalty_repeat_orders=LOYALTY_REPEAT_ORDERS,
                           loyalty_cooldown=LOYALTY_COOLDOWN_DAYS)


def _restaurar_stock(order):
    try:
        items = json.loads(order.items_json)
        for item in items:
            if item.get("is_combo"):
                for sub in item.get("combo_items", []):
                    p = Product.query.get(sub.get("id"))
                    if p and p.stock is not None:
                        p.stock += sub["cantidad"] * item["cantidad"]
                        if p.stock > 0:
                            p.activo = True
            else:
                p = Product.query.get(item.get("id"))
                if p and p.stock is not None:
                    p.stock += item["cantidad"]
                    if p.stock > 0:
                        p.activo = True
    except Exception:
        pass


def _cleanup_old_orders():
    """Borra automáticamente pedidos con más de 7 días. Restaura stock si estaban pendientes."""
    limite = datetime.utcnow() - timedelta(days=7)
    viejos = Order.query.filter(Order.fecha < limite).all()
    for o in viejos:
        if o.estado == "pendiente":
            _restaurar_stock(o)
            remove_loyalty_coupon_for_order(o)
        db.session.delete(o)
    if viejos:
        db.session.commit()


@admin_bp.route("/pedido/<int:oid>/delete", methods=["POST"])
@admin_required
def delete_pedido(oid):
    """Borrado manual de pedidos con más de 24 horas."""
    o = Order.query.get_or_404(oid)
    if datetime.utcnow() - o.fecha < timedelta(hours=24):
        return redirect(url_for("admin.dashboard") + "#tab-pedidos")
    if o.estado == "pendiente":
        _restaurar_stock(o)
        remove_loyalty_coupon_for_order(o)
    db.session.delete(o)
    db.session.commit()
    return redirect(url_for("admin.dashboard") + "#tab-pedidos")


@admin_bp.route("/pedido/<int:oid>/estado", methods=["POST"])
@admin_required
def update_estado(oid):
    o = Order.query.get_or_404(oid)
    nuevo = request.form.get("estado", o.estado)
    estado_anterior = o.estado
    if nuevo == "cancelado" and estado_anterior != "cancelado":
        _restaurar_stock(o)
        remove_loyalty_coupon_for_order(o)
    o.estado = nuevo
    reward_code = None
    if nuevo == "completado" and estado_anterior != "completado":
        db.session.flush()
        reward_code = maybe_generate_loyalty_coupon(o.user_id, order=o)
    db.session.commit()
    suffix = f"&reward={reward_code}" if reward_code else ""
    return redirect(url_for("admin.dashboard") + f"?updated={o.id}{suffix}#tab-pedidos")


@admin_bp.route("/producto/<int:pid>/precio", methods=["POST"])
@admin_required
def update_precio(pid):
    p = Product.query.get_or_404(pid)
    try:
        nuevo = int(request.form.get("precio", 0))
        if nuevo <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return redirect(url_for("admin.dashboard"))
    p.precio = nuevo
    db.session.commit()
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/producto/<int:pid>/toggle", methods=["POST"])
@admin_required
def toggle_producto(pid):
    p = Product.query.get_or_404(pid)
    p.activo = not p.activo
    db.session.commit()
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/producto/<int:pid>/resetprecio", methods=["POST"])
@admin_required
def reset_precio(pid):
    p = Product.query.get_or_404(pid)
    p.precio = p.precio_orig
    db.session.commit()
    return redirect(url_for("admin.dashboard"))


MAX_DESTACADOS = 12

TIPOS_VALIDOS = ["Res", "Cerdo", "Pollo", "Pescado", "Charcutería", "Lácteos", "Despensa"]
CATS_VALIDAS  = ["Premium", "Especiales", "Económicos", "Huesos"]

@admin_bp.route("/producto/<int:pid>/delete", methods=["POST"])
@admin_required
def delete_producto(pid):
    p = Product.query.get_or_404(pid)
    db.session.delete(p)
    db.session.commit()
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/producto/<int:pid>/editar", methods=["POST"])
@admin_required
def editar_producto(pid):
    p = Product.query.get_or_404(pid)

    nombre = request.form.get("nombre", "").strip()
    tipo   = request.form.get("tipo", "").strip()
    cat    = request.form.get("categoria", "").strip()
    desc   = request.form.get("descripcion", "").strip()
    emoji  = request.form.get("emoji", "").strip() or p.emoji

    if nombre:
        p.nombre = nombre
    if tipo in TIPOS_VALIDOS:
        p.tipo = tipo
    p.categoria = cat if cat in CATS_VALIDAS else p.tipo
    p.descripcion = desc
    p.emoji = emoji

    try:
        precio = int(request.form.get("precio", 0))
        if precio > 0:
            p.precio = precio
    except (ValueError, TypeError):
        pass

    stock_raw = request.form.get("stock", "SKIP")
    if stock_raw == "":
        p.stock = None
    elif stock_raw.isdigit():
        p.stock = int(stock_raw)
        if p.stock <= 0:
            p.stock = 0
            p.activo = False

    nueva_img = _save_image(request.files.get("imagen"))
    if nueva_img:
        p.imagen = nueva_img

    db.session.commit()
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/producto/crear", methods=["POST"])
@admin_required
def crear_producto():
    nombre = request.form.get("nombre", "").strip()
    tipo   = request.form.get("tipo", "").strip()
    cat    = request.form.get("categoria", "").strip()
    desc   = request.form.get("descripcion", "").strip()
    emoji  = request.form.get("emoji", "🥩").strip() or "🥩"

    if not nombre or tipo not in TIPOS_VALIDOS:
        return redirect(url_for("admin.dashboard"))

    try:
        precio = int(request.form.get("precio", 0))
        if precio <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return redirect(url_for("admin.dashboard"))

    stock_str = request.form.get("stock", "").strip()
    stock = int(stock_str) if stock_str.isdigit() else None

    imagen = _save_image(request.files.get("imagen"))

    p = Product(
        nombre=nombre, tipo=tipo,
        categoria=cat if cat in CATS_VALIDAS else tipo,
        precio=precio, precio_orig=precio,
        descripcion=desc, emoji=emoji,
        imagen=imagen, stock=stock, activo=True, destacado=False,
    )
    db.session.add(p)
    db.session.commit()
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/producto/<int:pid>/destacado", methods=["POST"])
@admin_required
def toggle_destacado(pid):
    p = Product.query.get_or_404(pid)
    if p.destacado:
        p.destacado = False
    else:
        count = Product.query.filter_by(destacado=True).count()
        if count < MAX_DESTACADOS:
            p.destacado = True
    db.session.commit()
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/producto/<int:pid>/stock", methods=["POST"])
@admin_required
def update_stock(pid):
    p = Product.query.get_or_404(pid)
    val = request.form.get("stock", "").strip()
    p.stock = int(val) if val.isdigit() else None
    if p.stock is not None and p.stock <= 0:
        p.stock = 0
        p.activo = False
    db.session.commit()
    return redirect(url_for("admin.dashboard"))


# ── Combos ────────────────────────────────────────────────────────────────────

@admin_bp.route("/combo/crear", methods=["POST"])
@admin_required
def crear_combo():
    nombre = request.form.get("nombre", "").strip()
    descripcion = request.form.get("descripcion", "").strip()
    emoji = request.form.get("emoji", "🎁").strip() or "🎁"
    fecha_inicio = _parse_date_field(request.form.get("fecha_inicio"))
    fecha_fin = _parse_date_field(request.form.get("fecha_fin"))
    try:
        precio = int(request.form.get("precio", 0))
        if precio <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return redirect(url_for("admin.dashboard") + "#tab-combos")
    if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
        return redirect(url_for("admin.dashboard") + "#tab-combos")

    items = []
    for p in Product.query.filter_by(activo=True).order_by(Product.id).all():
        qty_str = request.form.get(f"item_{p.id}", "").strip()
        if qty_str.isdigit() and int(qty_str) > 0:
            items.append({"id": p.id, "nombre": p.nombre, "cantidad": int(qty_str)})

    if not nombre or not items:
        return redirect(url_for("admin.dashboard") + "#tab-combos")

    combo = Combo(
        nombre=nombre, descripcion=descripcion, emoji=emoji,
        precio=precio, items_json=json.dumps(items, ensure_ascii=False),
        fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
    )
    db.session.add(combo)
    db.session.commit()
    return redirect(url_for("admin.dashboard") + "#tab-combos")


@admin_bp.route("/combo/<int:cid>/toggle", methods=["POST"])
@admin_required
def toggle_combo(cid):
    c = Combo.query.get_or_404(cid)
    c.activo = not c.activo
    db.session.commit()
    return redirect(url_for("admin.dashboard") + "#tab-combos")


@admin_bp.route("/combo/<int:cid>/delete", methods=["POST"])
@admin_required
def delete_combo(cid):
    c = Combo.query.get_or_404(cid)
    db.session.delete(c)
    db.session.commit()
    return redirect(url_for("admin.dashboard") + "#tab-combos")


@admin_bp.route("/combo/<int:cid>/precio", methods=["POST"])
@admin_required
def update_combo_precio(cid):
    c = Combo.query.get_or_404(cid)
    try:
        nuevo = int(request.form.get("precio", 0))
        if nuevo <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return redirect(url_for("admin.dashboard") + "#tab-combos")
    c.precio = nuevo
    db.session.commit()
    return redirect(url_for("admin.dashboard") + "#tab-combos")


@admin_bp.route("/combo/<int:cid>/vigencia", methods=["POST"])
@admin_required
def update_combo_vigencia(cid):
    c = Combo.query.get_or_404(cid)
    fecha_inicio = _parse_date_field(request.form.get("fecha_inicio"))
    fecha_fin = _parse_date_field(request.form.get("fecha_fin"))
    if fecha_inicio and fecha_fin and fecha_fin < fecha_inicio:
        return redirect(url_for("admin.dashboard") + "#tab-combos")
    c.fecha_inicio = fecha_inicio
    c.fecha_fin = fecha_fin
    db.session.commit()
    return redirect(url_for("admin.dashboard") + "#tab-combos")


# ── Promos ────────────────────────────────────────────────────────────────────

@admin_bp.route("/promo/crear", methods=["POST"])
@admin_required
def crear_promo():
    from datetime import date
    codigo = request.form.get("codigo", "").strip().upper()
    tipo   = request.form.get("tipo", "").strip()
    if not codigo or tipo not in ("porcentaje", "monto"):
        return redirect(url_for("admin.dashboard") + "#tab-promos")
    try:
        valor = int(request.form.get("valor", 0))
        if valor <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return redirect(url_for("admin.dashboard") + "#tab-promos")
    if tipo == "porcentaje" and valor > 100:
        valor = 100

    max_usos_str = request.form.get("max_usos", "").strip()
    max_usos = int(max_usos_str) if max_usos_str.isdigit() and int(max_usos_str) > 0 else None

    fecha_str = request.form.get("fecha_expira", "").strip()
    fecha_expira = None
    if fecha_str:
        try:
            fecha_expira = date.fromisoformat(fecha_str)
        except ValueError:
            pass

    if Promo.query.filter_by(codigo=codigo).first():
        return redirect(url_for("admin.dashboard") + "#tab-promos")

    visible_cliente = request.form.get("visible_cliente") == "on"
    p = Promo(
        codigo=codigo,
        tipo=tipo,
        valor=valor,
        max_usos=max_usos,
        fecha_expira=fecha_expira,
        visible_cliente=visible_cliente,
    )
    db.session.add(p)
    db.session.commit()
    return redirect(url_for("admin.dashboard") + "#tab-promos")


@admin_bp.route("/promo/<int:pid>/toggle", methods=["POST"])
@admin_required
def toggle_promo(pid):
    p = Promo.query.get_or_404(pid)
    p.activo = not p.activo
    db.session.commit()
    return redirect(url_for("admin.dashboard") + "#tab-promos")


@admin_bp.route("/promo/<int:pid>/visible", methods=["POST"])
@admin_required
def toggle_promo_visible(pid):
    p = Promo.query.get_or_404(pid)
    p.visible_cliente = not p.visible_cliente
    db.session.commit()
    return redirect(url_for("admin.dashboard") + "#tab-promos")


@admin_bp.route("/promo/<int:pid>/delete", methods=["POST"])
@admin_required
def delete_promo(pid):
    p = Promo.query.get_or_404(pid)
    db.session.delete(p)
    db.session.commit()
    return redirect(url_for("admin.dashboard") + "#tab-promos")


@admin_bp.route("/promo/<int:pid>/reset", methods=["POST"])
@admin_required
def reset_promo(pid):
    p = Promo.query.get_or_404(pid)
    p.veces_usado = 0
    db.session.commit()
    return redirect(url_for("admin.dashboard") + "#tab-promos")
