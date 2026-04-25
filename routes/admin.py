from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session
from config import ADMIN_PASSWORD
from model import get_all_products, _load_overrides, _save_overrides

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
    productos = get_all_products()
    return render_template("admin.html", productos=productos)


@admin_bp.route("/producto/<int:pid>/precio", methods=["POST"])
@admin_required
def update_precio(pid):
    try:
        nuevo = int(request.form.get("precio", 0))
        if nuevo <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return redirect(url_for("admin.dashboard"))
    ov = _load_overrides()
    ov.setdefault("prices", {})[str(pid)] = nuevo
    _save_overrides(ov)
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/producto/<int:pid>/toggle", methods=["POST"])
@admin_required
def toggle_producto(pid):
    ov = _load_overrides()
    disabled = set(ov.get("disabled", []))
    if pid in disabled:
        disabled.discard(pid)
    else:
        disabled.add(pid)
    ov["disabled"] = list(disabled)
    _save_overrides(ov)
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/producto/<int:pid>/resetprecio", methods=["POST"])
@admin_required
def reset_precio(pid):
    ov = _load_overrides()
    ov.get("prices", {}).pop(str(pid), None)
    _save_overrides(ov)
    return redirect(url_for("admin.dashboard"))
