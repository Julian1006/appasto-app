from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from database import db
from sqlalchemy import func
from model import User, Order, Promo

auth_bp = Blueprint("auth", __name__)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            flash("Inicia sesion para ver tu cuenta.", "info")
            return redirect(url_for("auth.login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def _next_url():
    nxt = request.args.get("next") or request.form.get("next")
    if nxt and nxt.startswith("/"):
        return nxt
    return url_for("auth.account")


@auth_bp.route("/registro", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        telefono = request.form.get("telefono", "").strip()
        direccion = request.form.get("direccion", "").strip()
        ciudad = request.form.get("ciudad", "").strip()

        if not nombre or not email or not password:
            error = "Completa nombre, correo y contrasena."
        elif len(password) < 8:
            error = "La contrasena debe tener minimo 8 caracteres."
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
            session.permanent = True
            session["user_id"] = user.id
            flash("Cuenta creada. Ya puedes comprar mas rapido.", "success")
            return redirect(_next_url())

    return render_template("login.html", mode="register", error=error, next_url=request.args.get("next", ""))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password_hash, password):
            error = "Correo o contrasena incorrectos."
        else:
            session.permanent = True
            session["user_id"] = user.id
            flash("Sesion iniciada.", "success")
            return redirect(_next_url())

    return render_template("login.html", mode="login", error=error, next_url=request.args.get("next", ""))


@auth_bp.route("/logout")
def logout():
    session.pop("user_id", None)
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
