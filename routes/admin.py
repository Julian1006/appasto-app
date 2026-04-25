from functools import wraps
from hmac import compare_digest
from time import time
from collections import defaultdict
from flask import Blueprint, render_template, request, redirect, url_for, session, abort
from config import ADMIN_PASSWORD
from database import db
from model import Product, Order

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
    return render_template("admin.html", productos=productos, pedidos=pedidos)


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
