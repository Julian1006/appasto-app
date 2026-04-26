import json
import os
import uuid
from functools import wraps
from hmac import compare_digest
from time import time
from collections import defaultdict
from flask import Blueprint, render_template, request, redirect, url_for, session, abort
from werkzeug.utils import secure_filename
from config import ADMIN_PASSWORD
from database import db
from model import Product, Order, Combo

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
    productos = Product.query.order_by(Product.id).all()
    pedidos   = Order.query.order_by(Order.fecha.desc()).all()
    combos    = Combo.query.order_by(Combo.id.desc()).all()
    n_dest    = Product.query.filter_by(destacado=True).count()
    return render_template("admin.html", productos=productos, pedidos=pedidos,
                           combos=combos, n_dest=n_dest, max_dest=MAX_DESTACADOS)


@admin_bp.route("/pedido/<int:oid>/estado", methods=["POST"])
@admin_required
def update_estado(oid):
    o = Order.query.get_or_404(oid)
    o.estado = request.form.get("estado", o.estado)
    db.session.commit()
    return redirect(url_for("admin.dashboard") + "#tab-pedidos")


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
    try:
        precio = int(request.form.get("precio", 0))
        if precio <= 0:
            raise ValueError
    except (ValueError, TypeError):
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
