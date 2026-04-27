from datetime import date, datetime, timedelta
import uuid
from sqlalchemy import func
from database import db
from model import Order, Promo, User

LOYALTY_REPEAT_COP      = 500_000   # Compras acumuladas desde el último cupón
LOYALTY_REPEAT_ORDERS   = 6         # O N pedidos completados desde el último cupón
LOYALTY_COOLDOWN_DAYS   = 7         # Días mínimos entre cupones
LOYALTY_DISCOUNT_PERCENT = 10       # % de descuento del cupón
LOYALTY_DAYS_VALID      = 7         # Días de validez del cupón emitido

# Mantenidos por compatibilidad con admin.py que los importa
LOYALTY_THRESHOLD = LOYALTY_REPEAT_COP


def _generate_loyalty_code():
    while True:
        code = f"APASTTO{uuid.uuid4().hex[:6].upper()}"
        if not Promo.query.filter_by(codigo=code).first():
            return code


def maybe_generate_loyalty_coupon(user_id, order=None):
    if not user_id:
        return None
    user = User.query.get(user_id)
    if not user:
        return None

    now = datetime.utcnow()

    # Si ya tiene un cupón activo sin usar → no emitir otro
    if user.reward_200k_code:
        promo = Promo.query.filter_by(codigo=user.reward_200k_code).first()
        if promo and promo.veces_usado == 0 and promo.is_valid()[0]:
            return None

    # Cooldown: mínimo 7 días desde el último cupón emitido
    if user.ultimo_reward_at:
        if (now - user.ultimo_reward_at).days < LOYALTY_COOLDOWN_DAYS:
            return None

    # Umbral: compras o pedidos completados desde el último cupón
    since = user.ultimo_reward_at or datetime(2000, 1, 1)
    total_since = db.session.query(func.coalesce(func.sum(Order.total), 0)).filter(
        Order.user_id == user.id,
        Order.estado == "completado",
        Order.fecha > since,
    ).scalar()
    count_since = Order.query.filter(
        Order.user_id == user.id,
        Order.estado == "completado",
        Order.fecha > since,
    ).count()

    if total_since < LOYALTY_REPEAT_COP and count_since < LOYALTY_REPEAT_ORDERS:
        return None

    # Emitir cupón
    code = _generate_loyalty_code()
    promo = Promo(
        codigo=code,
        tipo="porcentaje",
        valor=LOYALTY_DISCOUNT_PERCENT,
        max_usos=1,
        fecha_expira=date.today() + timedelta(days=LOYALTY_DAYS_VALID),
    )
    user.reward_200k_code = code
    user.ultimo_reward_at = now
    if order is not None:
        order.reward_code = code
    db.session.add(promo)
    return code


def remove_loyalty_coupon_for_order(order):
    code = getattr(order, "reward_code", None)
    if not code:
        return False

    promo = Promo.query.filter_by(codigo=code).first()
    if promo:
        db.session.delete(promo)

    if order.user_id:
        user = User.query.get(order.user_id)
        if user and user.reward_200k_code == code:
            user.reward_200k_code = None
            user.ultimo_reward_at = None

    order.reward_code = None
    return True
