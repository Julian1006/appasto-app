from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from database import db
from sqlalchemy import func
from model import User, Order, Promo
from security import MemoryRateLimiter, rotate_csrf_token, safe_next

auth_bp = Blueprint("auth", __name__)
_login_limiter = MemoryRateLimiter(max_attempts=8, window_seconds=900)
_register_limiter = MemoryRateLimiter(max_attempts=12, window_seconds=900)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            flash("Inicia sesion para ver tu cuenta.", "info")
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def _ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()


def _start_user_session(user):
    cart = session.get("cart")
    promo = session.get("promo")
    session.clear()
    if cart:
        session["cart"] = cart
    if promo:
        session["promo"] = promo
    session.permanent = True
    session["user_id"] = user.id
    rotate_csrf_token()


@auth_bp.route("/registro", methods=["GET", "POST"])
def register():
    error = None
    ip = _ip()
    if request.method == "POST":
        if _register_limiter.is_locked(ip):
            error = "Demasiados intentos. Espera 15 minutos antes de crear una cuenta."
            return render_template("login.html", mode="register", error=error, next_url=request.args.get("next", ""))

        nombre = request.form.get("nombre", "").strip()[:120]
        email = request.form.get("email", "").strip().lower()[:180]
        password = request.form.get("password", "")
        telefono = request.form.get("telefono", "").strip()[:30]
        direccion = request.form.get("direccion", "").strip()[:300]
        ciudad = request.form.get("ciudad", "").strip()[:100]

        if not nombre or not email or not password:
            error = "Completa nombre, correo y contrasena."
        elif len(password) < 8 or len(password) > 256:
            error = "La contrasena debe tener entre 8 y 256 caracteres."
        elif "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            error = "Ingresa un correo valido."
        elif User.query.filter_by(email=email).first():
            error = "Ese correo ya esta registrado. Inicia sesion."
        else:
            user = User(
                nombre=nombre,
                email=email,
                password_hash=generate_password_hash(password),
                telefono=telefono,
                direccion=direccion,
                ciudad=ciudad,
            )
            db.session.add(user)
            db.session.commit()
            _start_user_session(user)
            _register_limiter.reset(ip)
            flash("Cuenta creada. Ya puedes comprar mas rapido.", "success")
            return redirect(safe_next("auth.account"))

        _register_limiter.record_failure(ip)

    return render_template("login.html", mode="register", error=error, next_url=request.args.get("next", ""))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    ip = _ip()
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()[:180]
        password = request.form.get("password", "")
        key = f"{ip}:{email}"

        if _login_limiter.is_locked(key):
            error = "Demasiados intentos fallidos. Espera 15 minutos."
            return render_template("login.html", mode="login", error=error, next_url=request.args.get("next", ""))

        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password_hash, password):
            error = "Correo o contrasena incorrectos."
            _login_limiter.record_failure(key)
        else:
            _start_user_session(user)
            _login_limiter.reset(key)
            flash("Sesion iniciada.", "success")
            return redirect(safe_next("auth.account"))

    return render_template("login.html", mode="login", error=error, next_url=request.args.get("next", ""))


@auth_bp.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("admin", None)
    rotate_csrf_token()
    flash("Sesion cerrada.", "info")
    return redirect(url_for("main.index"))


@auth_bp.route("/cuenta")
@login_required
def account():
    user = User.query.get_or_404(session["user_id"])
    pedidos = Order.query.filter_by(user_id=user.id).order_by(Order.fecha.desc()).all()
    total_compras = db.session.query(func.coalesce(func.sum(Order.total), 0)).filter(
        Order.user_id == user.id,
        Order.estado == "completado",
    ).scalar()
    return render_template("account.html", user=user, pedidos=pedidos, total_compras=total_compras)


@auth_bp.route("/descuentos")
@login_required
def discounts():
    user = User.query.get_or_404(session["user_id"])
    reward = None
    if user.reward_200k_code:
        reward = Promo.query.filter_by(codigo=user.reward_200k_code).first()
        if reward and not reward.is_valid()[0]:
            reward = None

    promos = []
    for promo in Promo.query.filter_by(activo=True, visible_cliente=True).order_by(Promo.id.desc()).all():
        if promo.codigo == user.reward_200k_code:
            continue
        if promo.is_valid()[0]:
            promos.append(promo)

    return render_template("discounts.html", user=user, reward=reward, promos=promos)
