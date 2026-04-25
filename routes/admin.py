from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session
from config import ADMIN_PASSWORD
from database import db
from model import Product, Order

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin.dashboard"))
        error = "Contraseña incorrecta."
    return render_template("admin_login.html", error=error)


@admin_bp.route("/logout")
def logout():
    session.pop("admin", None)
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
    db.session.commit()
    return redirect(url_for("admin.dashboard"))
