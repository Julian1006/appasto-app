# =============================================================================
# model.py — Modelos SQLAlchemy y datos seed del catálogo
#
# MODELOS:
#   Order   → pedidos guardados al hacer checkout
#   Product → productos del catálogo (con stock, imagen, precio)
#   Combo   → combo de productos (precio fijo, descuenta stock de cada ingrediente)
#   Promo   → cupones de descuento (porcentaje o monto fijo COP)
#
# NOTAS IMPORTANTES:
#   - Product.stock = None significa stock ILIMITADO (no se controla)
#   - Product.activo = False lo oculta del catálogo y del carrito
#   - Cuando stock llega a 0, activo se pone False automáticamente (ver routes/cart.py)
#   - Combo.items_json guarda JSON: [{"id": <product_id>, "nombre": "...", "cantidad": <libras>}]
#   - Order.items_json guarda JSON con id de producto para poder restaurar stock al cancelar
#   - Promo.tipo: "porcentaje" (ej: 20 = 20% off) o "monto" (ej: 5000 = $5.000 off)
# =============================================================================

import json
from datetime import datetime, date as _date
from database import db


class Order(db.Model):
    __tablename__ = "orders"

    id        = db.Column(db.Integer, primary_key=True)
    user_id   = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    fecha     = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    metodo    = db.Column(db.String(30), nullable=False)   # WhatsApp, Nequi, Daviplata, Efectivo, Tarjeta
    total     = db.Column(db.Integer, nullable=False)       # Total en COP ya con descuento aplicado
    items_json= db.Column(db.Text, nullable=False)          # JSON con items (incluye id para restaurar stock)
    tel       = db.Column(db.String(30), default="")
    direccion = db.Column(db.String(300), default="")
    ciudad    = db.Column(db.String(100), default="")
    referencia= db.Column(db.String(50), default="")        # Referencia Wompi para pagos con tarjeta
    estado    = db.Column(db.String(20), default="pendiente")  # pendiente / completado / cancelado
    reward_code = db.Column(db.String(50), nullable=True)    # Cupón de fidelidad generado al completar este pedido

    @property
    def items(self):
        return json.loads(self.items_json)

    def to_dict(self):
        return {
            "id": self.id,
            "fecha": self.fecha.strftime("%d/%m/%Y %H:%M"),
            "metodo": self.metodo,
            "total": self.total,
            "items": self.items,
            "tel": self.tel,
            "direccion": self.direccion,
            "ciudad": self.ciudad,
            "referencia": self.referencia,
            "estado": self.estado,
        }


class User(db.Model):
    __tablename__ = "users"

    id            = db.Column(db.Integer, primary_key=True)
    nombre        = db.Column(db.String(120), nullable=False)
    email         = db.Column(db.String(180), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    telefono      = db.Column(db.String(30), default="")
    direccion     = db.Column(db.String(300), default="")
    ciudad        = db.Column(db.String(100), default="")
    reward_200k_issued = db.Column(db.Boolean, default=False, nullable=False, server_default="0")
    reward_200k_code   = db.Column(db.String(50), nullable=True)
    fecha_creado  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    pedidos = db.relationship("Order", backref="user", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "nombre": self.nombre,
            "email": self.email,
            "telefono": self.telefono,
            "direccion": self.direccion,
            "ciudad": self.ciudad,
        }


class Product(db.Model):
    __tablename__ = "products"

    id          = db.Column(db.Integer, primary_key=True)
    nombre      = db.Column(db.String(200), nullable=False)
    tipo        = db.Column(db.String(50))         # Res, Cerdo, Pollo, Pescado, Charcutería, Lácteos, Despensa
    categoria   = db.Column(db.String(50))         # Premium, Especiales, Económicos, Huesos
    precio      = db.Column(db.Integer, nullable=False)      # Precio actual en COP por libra
    precio_orig = db.Column(db.Integer, nullable=False)      # Precio original (para mostrar tachado si hay oferta)
    descripcion = db.Column(db.Text)
    emoji       = db.Column(db.String(20))
    stock       = db.Column(db.Integer, nullable=True)       # None = ilimitado; 0 = agotado
    destacado        = db.Column(db.Boolean, default=False, nullable=False, server_default="0")
    orden_destacado  = db.Column(db.Integer, default=0)        # 1-12 controla posición en home; 0 = sin orden
    badge            = db.Column(db.String(20), default="")    # Favorito | Popular | Premium | Nuevo | Oferta
    imagen           = db.Column(db.String(300), default="")
    activo           = db.Column(db.Boolean, default=True, nullable=False)

    @property
    def precio_modificado(self):
        # True si el precio fue cambiado manualmente desde el admin (precio != precio_orig)
        return self.precio != self.precio_orig

    def to_dict(self):
        return {
            "id": self.id,
            "nombre": self.nombre,
            "tipo": self.tipo,
            "categoria": self.categoria,
            "precio": self.precio,
            "precio_orig": self.precio_orig,
            "precio_modificado": self.precio_modificado,
            "descripcion": self.descripcion,
            "emoji": self.emoji,
            "imagen": self.imagen or "",
            "activo": self.activo,
            "badge": self.badge or "",
            "orden_destacado": self.orden_destacado or 0,
        }


def get_all_products():
    return [p.to_dict() for p in Product.query.order_by(Product.id).all()]


def get_product_by_id(product_id):
    p = Product.query.get(product_id)
    return p.to_dict() if p else None


class Combo(db.Model):
    # Un combo es un paquete de productos a precio fijo.
    # Al comprarse, descuenta el stock de cada producto incluido según su cantidad.
    __tablename__ = "combos"

    id          = db.Column(db.Integer, primary_key=True)
    nombre      = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text, default="")
    emoji       = db.Column(db.String(20), default="🎁")
    precio      = db.Column(db.Integer, nullable=False)
    items_json  = db.Column(db.Text, nullable=False, default="[]")  # [{"id": int, "nombre": str, "cantidad": int}]
    activo      = db.Column(db.Boolean, default=True, nullable=False)
    fecha_inicio= db.Column(db.Date, nullable=True)
    fecha_fin   = db.Column(db.Date, nullable=True)

    @property
    def items(self):
        return json.loads(self.items_json)

    def es_temporal(self):
        return self.fecha_inicio is not None or self.fecha_fin is not None

    def esta_vigente(self, today=None):
        today = today or _date.today()
        if self.fecha_inicio and today < self.fecha_inicio:
            return False
        if self.fecha_fin and today > self.fecha_fin:
            return False
        return True

    def estado_vigencia(self, today=None):
        today = today or _date.today()
        if self.fecha_inicio and today < self.fecha_inicio:
            return "programado"
        if self.fecha_fin and today > self.fecha_fin:
            return "vencido"
        if self.es_temporal():
            return "vigente"
        return "permanente"

    def to_dict(self):
        return {
            "id": self.id,
            "nombre": self.nombre,
            "descripcion": self.descripcion,
            "emoji": self.emoji,
            "precio": self.precio,
            "items": self.items,
            "activo": self.activo,
            "temporal": self.es_temporal(),
            "vigente": self.esta_vigente(),
            "estado_vigencia": self.estado_vigencia(),
            "fecha_inicio": self.fecha_inicio.isoformat() if self.fecha_inicio else None,
            "fecha_fin": self.fecha_fin.isoformat() if self.fecha_fin else None,
        }


def get_combo_by_id(cid):
    c = Combo.query.get(cid)
    return c.to_dict() if c else None


class Promo(db.Model):
    # Cupones de descuento que el cliente ingresa en el carrito.
    # tipo="porcentaje": valor=20 → 20% off del total
    # tipo="monto": valor=5000 → $5.000 off del total
    # max_usos=None → ilimitado; fecha_expira=None → sin vencimiento
    __tablename__ = "promos"

    id          = db.Column(db.Integer, primary_key=True)
    codigo      = db.Column(db.String(50), nullable=False, unique=True)   # Siempre en MAYÚSCULAS
    tipo        = db.Column(db.String(20), nullable=False)   # 'porcentaje' | 'monto'
    valor       = db.Column(db.Integer, nullable=False)       # % o COP
    activo      = db.Column(db.Boolean, default=True, nullable=False)
    visible_cliente = db.Column(db.Boolean, default=False, nullable=False, server_default="0")
    max_usos    = db.Column(db.Integer, nullable=True)        # None = ilimitado
    veces_usado = db.Column(db.Integer, default=0, nullable=False)
    fecha_expira= db.Column(db.Date, nullable=True)

    def calcular_descuento(self, total):
        if self.tipo == "porcentaje":
            return min(int(total * self.valor / 100), total)
        return min(self.valor, total)

    def is_valid(self):
        # Devuelve (True, "") si el cupón se puede usar, (False, "motivo") si no
        if not self.activo:
            return False, "El cupón está inactivo."
        if self.max_usos is not None and self.veces_usado >= self.max_usos:
            return False, "El cupón ya fue usado el máximo de veces."
        if self.fecha_expira and self.fecha_expira < _date.today():
            return False, "El cupón ha expirado."
        return True, ""

    def to_dict(self):
        return {
            "id": self.id, "codigo": self.codigo, "tipo": self.tipo,
            "valor": self.valor, "activo": self.activo,
            "visible_cliente": self.visible_cliente,
            "max_usos": self.max_usos, "veces_usado": self.veces_usado,
            "fecha_expira": self.fecha_expira.isoformat() if self.fecha_expira else None,
        }


class Categoria(db.Model):
    __tablename__ = "categorias"

    id      = db.Column(db.Integer, primary_key=True)
    nombre  = db.Column(db.String(50), nullable=False, unique=True)
    nivel   = db.Column(db.String(20), nullable=False)   # 'tipo' | 'subcategoria'
    emoji   = db.Column(db.String(10), default="")
    color   = db.Column(db.String(20), default="")
    activo  = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            "id": self.id, "nombre": self.nombre, "nivel": self.nivel,
            "emoji": self.emoji or "", "color": self.color or "", "activo": self.activo,
        }


SEED_CATEGORIAS = [
    {"nombre": "Res",         "nivel": "tipo",         "emoji": "🥩", "color": "#c0392b"},
    {"nombre": "Cerdo",       "nivel": "tipo",         "emoji": "🐷", "color": "#e67e22"},
    {"nombre": "Pollo",       "nivel": "tipo",         "emoji": "🍗", "color": "#f39c12"},
    {"nombre": "Pescado",     "nivel": "tipo",         "emoji": "🐟", "color": "#2980b9"},
    {"nombre": "Charcutería", "nivel": "tipo",         "emoji": "🌭", "color": "#8e44ad"},
    {"nombre": "Lácteos",     "nivel": "tipo",         "emoji": "🥛", "color": "#16a085"},
    {"nombre": "Despensa",    "nivel": "tipo",         "emoji": "🫙", "color": "#27ae60"},
    {"nombre": "Premium",     "nivel": "subcategoria", "emoji": "⭐", "color": "#f39c12"},
    {"nombre": "Especiales",  "nivel": "subcategoria", "emoji": "✨", "color": "#9b59b6"},
    {"nombre": "Económicos",  "nivel": "subcategoria", "emoji": "💰", "color": "#27ae60"},
    {"nombre": "Huesos",      "nivel": "subcategoria", "emoji": "🦴", "color": "#95a5a6"},
]


# ── Seed data (se carga una sola vez si la tabla está vacía) ──────────────────
# Para agregar más productos permanentes, añadirlos aquí y borrar la DB para re-seedear.
# En producción (Render) se puede agregar desde el admin sin tocar este archivo.
SEED_PRODUCTS = [
    # ===== RES - Premium =====
    {"id": 1,  "nombre": "Lomo fino entero",           "tipo": "Res",    "categoria": "Premium",      "precio": 30900, "descripcion": "Corte premium de alta calidad, tierno y jugoso.",              "emoji": "🥩", "imagen": "images/carne/Lomo-fino-entero.webp"},
    {"id": 2,  "nombre": "Lomo fino entero limpio",    "tipo": "Res",    "categoria": "Premium",      "precio": 35900, "descripcion": "Lomo fino sin grasa, listo para cocinar.",                    "emoji": "🥩", "imagen": "images/carne/Lomo-fino-entero-limpio.webp"},
    {"id": 3,  "nombre": "Lomo fino porcionado",       "tipo": "Res",    "categoria": "Premium",      "precio": 37900, "descripcion": "Lomo fino cortado en porciones individuales.",                "emoji": "🥩", "imagen": "images/carne/Lomo-fino-porcionado.webp"},
    {"id": 4,  "nombre": "Tomahawk",                   "tipo": "Res",    "categoria": "Premium",      "precio": 25900, "descripcion": "Corte premium con hueso largo, espectacular a la parrilla.", "emoji": "🥩", "imagen": "images/carne/Tomahawk.jpg"},
    {"id": 5,  "nombre": "T-bone",                     "tipo": "Res",    "categoria": "Premium",      "precio": 25900, "descripcion": "Corte premium con hueso y doble textura.",                   "emoji": "🥩", "imagen": "images/carne/T-bone.jpg"},
    {"id": 6,  "nombre": "Ribeye",                     "tipo": "Res",    "categoria": "Premium",      "precio": 23400, "descripcion": "Corte marmoleado de alto sabor, ideal a la parrilla.",       "emoji": "🥩", "imagen": "images/carne/Ribeye.webp"},
    {"id": 7,  "nombre": "Paletero de brazo",          "tipo": "Res",    "categoria": "Premium",      "precio": 18400, "descripcion": "Carne jugosa y con gran sabor del brazo de la res.",          "emoji": "🥩", "imagen": "images/carne/Paletero-de-brazo.webp"},
    # ===== RES - Especiales =====
    {"id": 8,  "nombre": "Cadera",                     "tipo": "Res",    "categoria": "Especiales",   "precio": 18400, "descripcion": "Corte versátil y rendidor, ideal para la mesa.",              "emoji": "🥩", "imagen": "images/carne/cadera.webp"},
    {"id": 9,  "nombre": "Bola",                       "tipo": "Res",    "categoria": "Especiales",   "precio": 18400, "descripcion": "Corte magro y equilibrado.",                                  "emoji": "🥩", "imagen": "images/carne/bola.webp"},
    {"id": 10, "nombre": "Centro de cadera",           "tipo": "Res",    "categoria": "Especiales",   "precio": 18400, "descripcion": "Corte firme y de excelente rendimiento.",                     "emoji": "🥩", "imagen": "images/carne/Centro-de-cadera.webp"},
    {"id": 11, "nombre": "Bota",                       "tipo": "Res",    "categoria": "Especiales",   "precio": 18400, "descripcion": "Corte con grasa y gran sabor.",                               "emoji": "🥩", "imagen": "images/carne/Bota.webp"},
    {"id": 12, "nombre": "Muchacho",                   "tipo": "Res",    "categoria": "Especiales",   "precio": 18400, "descripcion": "Corte limpio y de buena textura.",                            "emoji": "🥩", "imagen": "images/carne/Muchacho.webp"},
    {"id": 13, "nombre": "Chata",                      "tipo": "Res",    "categoria": "Especiales",   "precio": 23400, "descripcion": "Corte jugoso con buena grasa de sabor.",                      "emoji": "🥩", "imagen": "images/carne/chata.jpg"},
    {"id": 14, "nombre": "Punta de anca",              "tipo": "Res",    "categoria": "Especiales",   "precio": 23400, "descripcion": "Corte premium muy apetecido.",                                "emoji": "🥩", "imagen": "images/carne/Punta-de-anca.webp"},
    {"id": 15, "nombre": "Colita de cuadril",          "tipo": "Res",    "categoria": "Especiales",   "precio": 23400, "descripcion": "Corte jugoso y lleno de sabor.",                              "emoji": "🥩", "imagen": "images/carne/Colita-de-cuadril.webp"},
    {"id": 16, "nombre": "Morrillo",                   "tipo": "Res",    "categoria": "Especiales",   "precio": 16900, "descripcion": "Corte jugoso y lleno de sabor.",                              "emoji": "🥩", "imagen": "images/carne/Morrillo.webp"},
    {"id": 17, "nombre": "Falda de res",               "tipo": "Res",    "categoria": "Especiales",   "precio": 16900, "descripcion": "Corte delgado y versátil para múltiples preparaciones.",      "emoji": "🥩", "imagen": "images/carne/Falda-de-res.webp"},
    # ===== RES - Económicos =====
    {"id": 18, "nombre": "Sobrebarriga delgada",       "tipo": "Res",    "categoria": "Económicos",   "precio": 16900, "descripcion": "Carne delgada y versátil, ideal para sudados.",               "emoji": "🥩", "imagen": "images/carne/sobrebarriga-delgada.webp"},
    {"id": 19, "nombre": "Pecho / Sobrebarriga gruesa","tipo": "Res",    "categoria": "Económicos",   "precio": 16900, "descripcion": "Sobrebarriga gruesa (Pecho/Brisket), ideal para cocción lenta.","emoji": "🥩", "imagen": "images/carne/sobrebarriga-gruesa.webp"},
    {"id": 20, "nombre": "Carne desmechar",            "tipo": "Res",    "categoria": "Económicos",   "precio": 16900, "descripcion": "Corte suave y rendidor, ideal para desmechar.",                "emoji": "🥩", "imagen": "images/carne/Carne-desmechar.webp"},
    {"id": 21, "nombre": "Goulash",                    "tipo": "Res",    "categoria": "Económicos",   "precio": 16900, "descripcion": "Corte versátil, ideal para el día a día.",                    "emoji": "🥩", "imagen": "images/carne/Goulash.webp"},
    {"id": 22, "nombre": "Asado de tira",              "tipo": "Res",    "categoria": "Económicos",   "precio": 16900, "descripcion": "Corte con hueso lleno de sabor.",                             "emoji": "🍖", "imagen": "images/carne/Asado-de-tira.webp"},
    {"id": 23, "nombre": "Costilla",                   "tipo": "Res",    "categoria": "Económicos",   "precio": 14900, "descripcion": "Corte jugoso y tradicional.",                                 "emoji": "🍖", "imagen": "images/carne/costilla.webp"},
    {"id": 24, "nombre": "Murillo",                    "tipo": "Res",    "categoria": "Económicos",   "precio": 16900, "descripcion": "Corte rendidor y de gran sabor.",                             "emoji": "🥩", "imagen": "images/carne/Murillo.webp"},
    {"id": 25, "nombre": "Osobuco",                    "tipo": "Res",    "categoria": "Económicos",   "precio": 14900, "descripcion": "Corte con hueso y médula, ideal para guisos.",                "emoji": "🍖", "imagen": "images/carne/Osobuco.webp"},
    {"id": 26, "nombre": "Cola",                       "tipo": "Res",    "categoria": "Económicos",   "precio": 14900, "descripcion": "Corte gelatinoso y muy sabroso.",                             "emoji": "🥩", "imagen": "images/carne/Cola.webp"},
    # ===== RES - Huesos =====
    {"id": 27, "nombre": "Hueso de paleta",            "tipo": "Res",    "categoria": "Huesos",       "precio": 16900, "descripcion": "Hueso con carne y gran sabor para caldos.",                   "emoji": "🦴", "imagen": ""},
    {"id": 28, "nombre": "Hueso carnudo",              "tipo": "Res",    "categoria": "Huesos",       "precio":  4900, "descripcion": "Hueso con abundante carne, ideal para sopas.",                "emoji": "🦴", "imagen": "images/carne/hueso-carnudo.webp"},
    # ===== CERDO - Especiales =====
    {"id": 29, "nombre": "Panceta",                    "tipo": "Cerdo",  "categoria": "Especiales",   "precio": 16900, "descripcion": "Corte de cerdo jugoso con gran sabor.",                       "emoji": "🐷", "imagen": "images/cerdo/Panceta.webp"},
    {"id": 30, "nombre": "Lomo de cerdo",              "tipo": "Cerdo",  "categoria": "Especiales",   "precio": 15900, "descripcion": "Corte magro y suave, desde 250g.",                            "emoji": "🐷", "imagen": "images/cerdo/Lomo-de-cerdo.webp"},
    {"id": 31, "nombre": "Costilla de cerdo",          "tipo": "Cerdo",  "categoria": "Especiales",   "precio": 15900, "descripcion": "Corte de cerdo jugoso y tradicional.",                        "emoji": "🐷", "imagen": "images/cerdo/Costilla-de-cerdo.webp"},
    {"id": 32, "nombre": "Costilla de cerdo con piel", "tipo": "Cerdo",  "categoria": "Especiales",   "precio": 15900, "descripcion": "Corte con piel tipo sparring.",                               "emoji": "🐷", "imagen": "images/cerdo/Costilla-de-cerdo-con-piel.webp"},
    {"id": 33, "nombre": "Costilla San Luis",          "tipo": "Cerdo",  "categoria": "Especiales",   "precio": 15900, "descripcion": "Corte limpio y parejo, desde 250g.",                          "emoji": "🐷", "imagen": "images/cerdo/Costilla-de-cerdo-san-luis.webp"},
    # ===== CERDO - Económicos =====
    {"id": 34, "nombre": "Chuleta de lomo",            "tipo": "Cerdo",  "categoria": "Económicos",   "precio": 14900, "descripcion": "Corte de cerdo jugoso listo para cocinar.",                   "emoji": "🐷", "imagen": "images/cerdo/Chuleta-de-lomo.webp"},
    {"id": 35, "nombre": "Pierna",                     "tipo": "Cerdo",  "categoria": "Económicos",   "precio": 14900, "descripcion": "Corte de cerdo tradicional y rendidor.",                      "emoji": "🐷", "imagen": "images/cerdo/Pierna.webp"},
    {"id": 36, "nombre": "Pierna con hueso y piel",    "tipo": "Cerdo",  "categoria": "Económicos",   "precio": 14900, "descripcion": "Corte de cerdo tradicional y rendidor.",                      "emoji": "🐷", "imagen": "images/cerdo/Pierna-con-hueso-y-piel.webp"},
    {"id": 37, "nombre": "Bondiola",                   "tipo": "Cerdo",  "categoria": "Económicos",   "precio": 14900, "descripcion": "Corte marmoleado y muy jugoso.",                              "emoji": "🐷", "imagen": "images/cerdo/Bondiola.webp"},
    # ===== CERDO - Huesos =====
    {"id": 38, "nombre": "Pezuna",                     "tipo": "Cerdo",  "categoria": "Huesos",       "precio":  6400, "descripcion": "Corte de cerdo tradicional lleno de sabor.",                  "emoji": "🐷", "imagen": "images/cerdo/Pezuna.webp"},
    # ===== POLLO =====
    {"id": 39, "nombre": "Pechuga entera",             "tipo": "Pollo",  "categoria": "Económicos",   "precio": 10900, "descripcion": "Corte magro, fresco y versátil.",                             "emoji": "🍗", "imagen": "images/pollo/Pechuga-entera.webp"},
    {"id": 40, "nombre": "Filete de pechuga",          "tipo": "Pollo",  "categoria": "Económicos",   "precio": 14900, "descripcion": "Filete de pechuga sin hueso, listo para cocinar.",            "emoji": "🍗", "imagen": "images/pollo/Filete-de-pechuga.webp"},
    {"id": 41, "nombre": "Pierna pernil",              "tipo": "Pollo",  "categoria": "Económicos",   "precio":  7900, "descripcion": "Corte magro, fresco y versátil.",                             "emoji": "🍗", "imagen": "images/pollo/Pierna-pernil.webp"},
    {"id": 42, "nombre": "Churrasco de pollo",         "tipo": "Pollo",  "categoria": "Económicos",   "precio":  9900, "descripcion": "Pierna pernil sin hueso, ideal a la parrilla.",               "emoji": "🍗", "imagen": "images/pollo/Churrasco-de-pollo.webp"},
    {"id": 43, "nombre": "Muslo",                      "tipo": "Pollo",  "categoria": "Económicos",   "precio":  8000, "descripcion": "Corte magro, fresco y versátil.",                             "emoji": "🍗", "imagen": "images/pollo/Muslo.webp"},
    {"id": 44, "nombre": "Contra muslo",               "tipo": "Pollo",  "categoria": "Económicos",   "precio":  8000, "descripcion": "Corte magro, fresco y versátil.",                             "emoji": "🍗", "imagen": "images/pollo/Contra-muslo.webp"},
    {"id": 45, "nombre": "Ala",                        "tipo": "Pollo",  "categoria": "Económicos",   "precio":  7900, "descripcion": "Corte magro, fresco y versátil.",                             "emoji": "🍗", "imagen": "images/pollo/Ala.webp"},
    {"id": 46, "nombre": "Colombina de ala",           "tipo": "Pollo",  "categoria": "Económicos",   "precio": 11900, "descripcion": "Corte magro, fresco y versátil.",                             "emoji": "🍗", "imagen": "images/pollo/Colombina-de-ala.webp"},
    {"id": 47, "nombre": "Corazones de pollo",         "tipo": "Pollo",  "categoria": "Económicos",   "precio":  7900, "descripcion": "Corte magro, fresco y versátil.",                             "emoji": "🍗", "imagen": "images/pollo/Corazones-de-pollo.webp"},
    {"id": 48, "nombre": "Mollejas de pollo",          "tipo": "Pollo",  "categoria": "Económicos",   "precio":  7900, "descripcion": "Corte magro, fresco y versátil.",                             "emoji": "🍗", "imagen": "images/pollo/Mollejas-de-pollo.webp"},
    {"id": 57, "nombre": "Hígado de pollo",            "tipo": "Pollo",  "categoria": "Económicos",   "precio":  7900, "descripcion": "Corte magro, fresco y versátil.",                             "emoji": "🍗", "imagen": "images/pollo/Higado-de-pollo.webp"},
    {"id": 58, "nombre": "Menudencias",                "tipo": "Pollo",  "categoria": "Económicos",   "precio":  3000, "descripcion": "Corte magro, fresco y versátil.",                             "emoji": "🍗", "imagen": "images/pollo/Menudencias.webp"},
    # ===== PESCADO - Premium =====
    {"id": 49, "nombre": "Filete de salmón",           "tipo": "Pescado","categoria": "Premium",      "precio": 36900, "descripcion": "Filete premium, fresco y nutritivo.",                         "emoji": "🐟", "imagen": "images/pescado/Filete-de-salmon.webp"},
    {"id": 50, "nombre": "Filete de atún",             "tipo": "Pescado","categoria": "Premium",      "precio": 36900, "descripcion": "Filete premium, fresco y nutritivo.",                         "emoji": "🐟", "imagen": "images/pescado/Filete-de-atun.webp"},
    {"id": 51, "nombre": "Camarón precocido",          "tipo": "Pescado","categoria": "Premium",      "precio": 24900, "descripcion": "Camarón fresco precocido, listo para usar.",                  "emoji": "🦐", "imagen": "images/pescado/Camaron-precocido.webp"},
    {"id": 59, "nombre": "Camarón crudo",              "tipo": "Pescado","categoria": "Premium",      "precio": 24900, "descripcion": "Camarón fresco crudo, ideal para parrilla.",                  "emoji": "🦐", "imagen": "images/pescado/Camaron-Crudo.webp"},
    # ===== PESCADO - Especiales =====
    {"id": 52, "nombre": "Bagre dorado",               "tipo": "Pescado","categoria": "Especiales",   "precio": 22900, "descripcion": "Pescado fresco y nutritivo.",                                 "emoji": "🐟", "imagen": "images/pescado/Bagre-dorado.webp"},
    {"id": 53, "nombre": "Trucha deshuesada",          "tipo": "Pescado","categoria": "Especiales",   "precio": 15900, "descripcion": "Trucha sin espinas, lista para cocinar.",                     "emoji": "🐟", "imagen": "images/pescado/Trucha-deshuesada.webp"},
    {"id": 54, "nombre": "Mojarra",                    "tipo": "Pescado","categoria": "Especiales",   "precio": 15900, "descripcion": "Pescado fresco y nutritivo.",                                 "emoji": "🐟", "imagen": "images/pescado/Mojarra.webp"},
    # ===== PESCADO - Económicos =====
    {"id": 55, "nombre": "Filete de tilapia",          "tipo": "Pescado","categoria": "Económicos",   "precio": 14900, "descripcion": "Filete fresco y nutritivo.",                                  "emoji": "🐟", "imagen": "images/pescado/Filete-de-tilapia.webp"},
    {"id": 56, "nombre": "Bandeja de basa",            "tipo": "Pescado","categoria": "Económicos",   "precio": 10900, "descripcion": "Bandeja de filete de basa, fresco y nutritivo.",              "emoji": "🐟", "imagen": "images/pescado/Bandeja-de-basa.webp"},
    # ===== CHARCUTERÍA =====
    {"id": 60, "nombre": "Chorizo fazenda 640g",        "tipo": "Charcutería","categoria": "Premium",   "precio": 26900, "descripcion": "Chorizo artesanal fazenda 640g.",              "emoji": "🌭", "imagen": "images/charcuteria/Chorizo-fazenda.webp"},
    {"id": 61, "nombre": "Chorizo fazenda coctel 300g", "tipo": "Charcutería","categoria": "Especiales","precio": 15900, "descripcion": "Chorizo cóctel fazenda 300g.",                 "emoji": "🌭", "imagen": "images/charcuteria/Chorizo-fazenda-coctel.webp"},
    {"id": 62, "nombre": "Chorizo fazenda mixto 1kg",   "tipo": "Charcutería","categoria": "Premium",   "precio": 39900, "descripcion": "Chorizo mixto fazenda 1000g.",                 "emoji": "🌭", "imagen": "images/charcuteria/Chorizo-fazenda-mixto.webp"},
    {"id": 63, "nombre": "Morcilla casera fazenda 500g","tipo": "Charcutería","categoria": "Especiales","precio": 14900, "descripcion": "Morcilla artesanal casera fazenda 500g.",      "emoji": "🌭", "imagen": "images/charcuteria/Morcilla-casera-fazenda.webp"},
    {"id": 64, "nombre": "Morcilla cóctel fazenda 300g","tipo": "Charcutería","categoria": "Especiales","precio":  9900, "descripcion": "Morcilla cóctel fazenda 300g.",                "emoji": "🌭", "imagen": "images/charcuteria/Morcilla-coctel-fazenda.webp"},
    {"id": 65, "nombre": "Costillitas ahumadas 500g",   "tipo": "Charcutería","categoria": "Especiales","precio": 17900, "descripcion": "Costillitas ahumadas fazenda 500g.",           "emoji": "🌭", "imagen": "images/charcuteria/Costillitas-ahumadas-fazenda.webp"},
    {"id": 66, "nombre": "Salchichón fazenda 500g",     "tipo": "Charcutería","categoria": "Especiales","precio": 13900, "descripcion": "Salchichón artesanal fazenda 500g.",           "emoji": "🌭", "imagen": "images/charcuteria/Salchichon-fazenda.webp"},
    {"id": 67, "nombre": "Tocineta ahumada 150g",       "tipo": "Charcutería","categoria": "Especiales","precio": 14900, "descripcion": "Tocineta ahumada 150g.",                       "emoji": "🥓", "imagen": "images/charcuteria/Tocineta-ahumada.webp"},
    {"id": 68, "nombre": "Chorizo argentino 500g",      "tipo": "Charcutería","categoria": "Premium",   "precio": 32900, "descripcion": "Chorizo estilo argentino 500g.",               "emoji": "🌭", "imagen": "images/charcuteria/Chorizo-argentino.webp"},
    {"id": 69, "nombre": "Chorizo antioqueño 500g",     "tipo": "Charcutería","categoria": "Especiales","precio": 32900, "descripcion": "Chorizo antioqueño artesanal 500g.",           "emoji": "🌭", "imagen": "images/charcuteria/Chorizo-antioqueno.webp"},
    {"id": 70, "nombre": "Chorizo español 500g",        "tipo": "Charcutería","categoria": "Premium",   "precio": 37900, "descripcion": "Chorizo español curado 500g.",                 "emoji": "🌭", "imagen": "images/charcuteria/Chorizo-espanol.webp"},
    {"id": 71, "nombre": "Morcilla antioqueña 500g",    "tipo": "Charcutería","categoria": "Especiales","precio": 23900, "descripcion": "Morcilla antioqueña artesanal 500g.",          "emoji": "🌭", "imagen": "images/charcuteria/Morcilla-antioquena.webp"},
    {"id": 72, "nombre": "Morcilla Burgos 500g",        "tipo": "Charcutería","categoria": "Premium",   "precio": 30900, "descripcion": "Morcilla estilo Burgos 500g.",                 "emoji": "🌭", "imagen": "images/charcuteria/Morcilla-Burgos.webp"},
    # ===== LÁCTEOS Y HUEVOS =====
    {"id": 73, "nombre": "Huevo gentil AA x30",         "tipo": "Lácteos","categoria": "Especiales",  "precio": 24900, "descripcion": "Huevos Gentil AA, cartón x30 unidades.",        "emoji": "🥚", "imagen": "images/lacteos/Huevo-gentil-AA-x30.webp"},
    {"id": 74, "nombre": "Huevo gentil AA x12",         "tipo": "Lácteos","categoria": "Especiales",  "precio": 11900, "descripcion": "Huevos Gentil AA, cartón x12 unidades.",        "emoji": "🥚", "imagen": "images/lacteos/Huevo-gentil-AA-x12.webp"},
    {"id": 75, "nombre": "Huevo AAA x30",               "tipo": "Lácteos","categoria": "Especiales",  "precio": 17900, "descripcion": "Huevos AAA, cartón x30 unidades.",              "emoji": "🥚", "imagen": "images/lacteos/Huevo-AAA-x30.webp"},
    {"id": 76, "nombre": "Huevo AA x30",                "tipo": "Lácteos","categoria": "Económicos",  "precio": 16500, "descripcion": "Huevos AA, cartón x30 unidades.",               "emoji": "🥚", "imagen": "images/lacteos/Huevo-AA-x30.webp"},
    {"id": 77, "nombre": "Queso costeño",               "tipo": "Lácteos","categoria": "Especiales",  "precio": 16500, "descripcion": "Queso costeño fresco por libra.",               "emoji": "🧀", "imagen": "images/lacteos/Queso-Costeno.webp"},
    {"id": 78, "nombre": "Queso campesino",             "tipo": "Lácteos","categoria": "Especiales",  "precio": 15000, "descripcion": "Queso campesino fresco por libra.",             "emoji": "🧀", "imagen": "images/lacteos/Queso-campesino.webp"},
    {"id": 79, "nombre": "Leche Pomar entera six pack", "tipo": "Lácteos","categoria": "Especiales",  "precio": 34900, "descripcion": "Leche Pomar entera six pack 1.1L.",             "emoji": "🥛", "imagen": "images/lacteos/Six-pack-Leche-pomar-entera.webp"},
    {"id": 80, "nombre": "Leche Pomar deslact. six pack","tipo": "Lácteos","categoria": "Especiales", "precio": 34900, "descripcion": "Leche Pomar deslactosada six pack 1.1L.",      "emoji": "🥛", "imagen": "images/lacteos/Six-pack-Leche-deslactosada-pomar.webp"},
    {"id": 81, "nombre": "Leche Pomar entera 1.1L",    "tipo": "Lácteos","categoria": "Económicos",   "precio":  5900, "descripcion": "Leche Pomar entera 1100ml.",                    "emoji": "🥛", "imagen": "images/lacteos/Leche-pomar-entera.webp"},
    {"id": 82, "nombre": "Leche Alpina entera six pack","tipo": "Lácteos","categoria": "Premium",     "precio": 44900, "descripcion": "Leche Alpina entera six pack 1.1L.",            "emoji": "🥛", "imagen": "images/lacteos/Six-pack-leche-entera-alpina.webp"},
    {"id": 83, "nombre": "Leche Alpina entera 1.1L",   "tipo": "Lácteos","categoria": "Económicos",   "precio":  7900, "descripcion": "Leche Alpina entera 1100ml.",                   "emoji": "🥛", "imagen": "images/lacteos/Leche-entera-alpina.webp"},
    {"id": 84, "nombre": "Queso parmesano Alpina 100g", "tipo": "Lácteos","categoria": "Premium",     "precio": 14500, "descripcion": "Queso parmesano rallado Alpina 100g.",          "emoji": "🧀", "imagen": "images/lacteos/Queso-parmesano-alpina-100gr.webp"},
    {"id": 85, "nombre": "Queso holandés Alpina 450g",  "tipo": "Lácteos","categoria": "Premium",     "precio": 39900, "descripcion": "Queso holandés Alpina 450g.",                   "emoji": "🧀", "imagen": "images/lacteos/Queso-holandes-alpina-450gr.webp"},
    {"id": 86, "nombre": "Mantequilla Alpina con sal",  "tipo": "Lácteos","categoria": "Especiales",  "precio": 11500, "descripcion": "Mantequilla con sal Alpina 125g.",              "emoji": "🧈", "imagen": "images/lacteos/Mantequilla-con-sal-alpina-125gr.webp"},
    # ===== DESPENSA =====
    {"id": 87, "nombre": "Ghee Fubafala 400g",          "tipo": "Despensa","categoria": "Premium",    "precio": 55000, "descripcion": "Mantequilla clarificada Ghee 100% pura Fubafala 400g.", "emoji": "🫙", "imagen": "images/despensa/Ghee-fubafala-400g.webp"},
    {"id": 88, "nombre": "Ghee Fubafala 200g",          "tipo": "Despensa","categoria": "Premium",    "precio": 28500, "descripcion": "Mantequilla clarificada Ghee 100% pura Fubafala 200g.", "emoji": "🫙", "imagen": "images/despensa/Ghee-fubafala-200g.webp"},
    {"id": 89, "nombre": "Ghee vaca A2 200g",           "tipo": "Despensa","categoria": "Premium",    "precio": 28000, "descripcion": "Mantequilla clarificada Ghee premium de vaca A2 200g.", "emoji": "🫙", "imagen": "images/despensa/Ghee-vaca-A2-200g.webp"},
    # ===== RES - Molidas =====
    {"id": 90, "nombre": "Molida especial 500g",        "tipo": "Res",    "categoria": "Económicos",  "precio": 15900, "descripcion": "Selección balanceada de carne magra.",                   "emoji": "🥩", "imagen": "images/carne/Molida-especial.webp"},
    {"id": 91, "nombre": "Molida Apastto 90/10",        "tipo": "Res",    "categoria": "Económicos",  "precio": 15900, "descripcion": "Alta en proteína y baja en grasa.",                      "emoji": "🥩", "imagen": "images/carne/Molida-apastto.webp"},
    {"id": 92, "nombre": "Molida 80/20 500g",           "tipo": "Res",    "categoria": "Económicos",  "precio": 15900, "descripcion": "Mayor jugosidad y sabor intenso.",                       "emoji": "🥩", "imagen": "images/carne/Molida-80-20.webp"},
    # ===== CERDO - Nuevos cortes =====
    {"id": 93, "nombre": "Milanesa de cerdo 500g",      "tipo": "Cerdo",  "categoria": "Especiales",  "precio": 14900, "descripcion": "Corte tradicional y rendidor.",                          "emoji": "🐷", "imagen": "images/cerdo/Milanesa-de-cerdo.webp"},
    {"id": 94, "nombre": "Goulash de cerdo 500g",       "tipo": "Cerdo",  "categoria": "Especiales",  "precio": 14900, "descripcion": "Corte versátil de cerdo para el día a día.",             "emoji": "🐷", "imagen": "images/cerdo/Goulash-de-cerdo.webp"},
    {"id": 95, "nombre": "Osobuco de cerdo 500g",       "tipo": "Cerdo",  "categoria": "Huesos",      "precio": 14900, "descripcion": "Corte con hueso y piel, ideal para guisos.",             "emoji": "🐷", "imagen": "images/cerdo/Osobuco-de-cerdo.webp"},
    {"id": 96, "nombre": "Huesitos de marrano 500g",    "tipo": "Cerdo",  "categoria": "Huesos",      "precio": 14900, "descripcion": "Corte tradicional de cerdo para caldos.",                "emoji": "🐷", "imagen": "images/cerdo/Huesitos-de-marrano.webp"},
    {"id": 97, "nombre": "Chuleta mariposa 500g",       "tipo": "Cerdo",  "categoria": "Especiales",  "precio": 14900, "descripcion": "Corte jugoso listo para cocinar.",                       "emoji": "🐷", "imagen": "images/cerdo/Chuleta-mariposa.webp"},
    {"id": 98, "nombre": "Chuleta de brazo 500g",       "tipo": "Cerdo",  "categoria": "Huesos",      "precio": 14900, "descripcion": "Corte con hueso jugoso listo para cocinar.",             "emoji": "🐷", "imagen": "images/cerdo/Chuleta-de-brazo.webp"},
    # ===== LÁCTEOS - Nuevos =====
    {"id": 99, "nombre": "Mantequilla sin sal Alpina",  "tipo": "Lácteos","categoria": "Especiales",  "precio": 11500, "descripcion": "Mantequilla sin sal Alpina 125g.",                       "emoji": "🧈", "imagen": "images/lacteos/Mantequilla-sin-sal-alpina-125gr.webp"},
    {"id":100, "nombre": "Queso holandés Alpina 250g",  "tipo": "Lácteos","categoria": "Premium",     "precio": 24900, "descripcion": "Queso holandés Alpina 250g.",                            "emoji": "🧀", "imagen": "images/lacteos/Queso-holandes-alpina-250gr.webp"},
    {"id":101, "nombre": "Queso parmesano Alpina 40g",  "tipo": "Lácteos","categoria": "Económicos",  "precio":  6900, "descripcion": "Queso parmesano rallado Alpina 40g.",                    "emoji": "🧀", "imagen": "images/lacteos/Queso-parmesano-alpina-40gr.webp"},
    {"id":102, "nombre": "Leche Pomar deslact. 1.1L",   "tipo": "Lácteos","categoria": "Económicos",  "precio":  6900, "descripcion": "Leche deslactosada Pomar 1100ml.",                       "emoji": "🥛", "imagen": "images/lacteos/Leche-pomar-deslactosada.webp"},
    # ===== CHARCUTERÍA - Nuevo tamaño =====
    {"id":103, "nombre": "Chorizo fazenda 120g",        "tipo": "Charcutería","categoria": "Económicos","precio": 6900, "descripcion": "Por 2 unidades, chorizo artesanal Fazenda.",           "emoji": "🌭", "imagen": "images/charcuteria/Chorizo-fazenda-120g.webp"},
    # ===== DESPENSA - Experiencia parrillera =====
    {"id":104, "nombre": "Carbón Santa Fuego 2.5kg",    "tipo": "Despensa","categoria": "Premium",    "precio": 28500, "descripcion": "Calor intenso y larga duración.",                        "emoji": "🔥", "imagen": "images/despensa/Carbon-premium.webp"},
    {"id":105, "nombre": "Barril parrillero pequeño",   "tipo": "Despensa","categoria": "Premium",    "precio": 390000,"descripcion": "15 a 20 lb. Incluye carbonera y termómetro interior.",  "emoji": "🍖", "imagen": "images/despensa/Barril-pequeno.webp"},
    {"id":106, "nombre": "Combo parrillero Apastto",    "tipo": "Despensa","categoria": "Premium",    "precio": 499000,"descripcion": "Incluye barril parrillero 15 a 20 lb.",                 "emoji": "🍖", "imagen": "images/despensa/Combo-parrillero.webp"},
    {"id":107, "nombre": "Barril parrillero mediano",   "tipo": "Despensa","categoria": "Premium",    "precio": 890000,"descripcion": "30 a 35 lb. Incluye parrilla abatible y carbonera.",    "emoji": "🍖", "imagen": "images/despensa/Barril-mediano.webp"},
    {"id":108, "nombre": "Barril parrillero premium",   "tipo": "Despensa","categoria": "Premium",    "precio":1590000,"descripcion": "70 lb. Alta capacidad para grandes reuniones.",          "emoji": "🍖", "imagen": "images/despensa/Barril-premium.webp"},
]
