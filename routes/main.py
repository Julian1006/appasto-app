from flask import Blueprint, render_template, request, jsonify
import random
from model import get_all_products

main_bp = Blueprint("main", __name__)

TABS = ["Todos", "Res", "Cerdo", "Pollo", "Pescado", "Charcutería", "Lácteos", "Despensa", "Premium", "Especiales", "Económicos", "Huesos"]
TIPOS = ["Res", "Cerdo", "Pollo", "Pescado", "Charcutería", "Lácteos", "Despensa"]
CATEGORIAS = ["Premium", "Especiales", "Económicos", "Huesos"]

DESTACADOS_IDS = [4, 5, 6, 1, 3, 29, 31, 49, 60, 73, 87, 8]  # fallback solo si DB vacía

LOW_STOCK = {2, 5, 14, 29, 49, 60}


@main_bp.route("/")
def index():
    from model import Product, Combo
    todos = [p for p in get_all_products() if p.get("activo", True)]
    id_map = {p["id"]: p for p in todos}
    dest_prods = Product.query.filter_by(destacado=True).all()
    if dest_prods:
        dest_prods.sort(key=lambda p: (p.orden_destacado if p.orden_destacado and p.orden_destacado > 0 else 999, p.id))
        destacados = [id_map[p.id] for p in dest_prods if p.id in id_map]
    else:
        destacados = [id_map[i] for i in DESTACADOS_IDS if i in id_map]
    prod_map = {p.id: p for p in Product.query.all()}
    combos = [
        c for c in Combo.query.filter_by(activo=True).order_by(Combo.id).all()
        if c.esta_vigente() and all(
            (p := prod_map.get(item["id"])) and p.activo and
            (p.stock is None or p.stock >= item["cantidad"])
            for item in c.items
        )
    ]
    return render_template("index.html", productos=destacados,
                           low_stock=LOW_STOCK, combos=combos,
                           productos_count=len(todos))


@main_bp.route("/nosotros")
def nosotros():
    return render_template("nosotros.html")


@main_bp.route("/catalogo")
def catalogo():
    filtro = request.args.get("filtro", "Todos")
    todos = [p for p in get_all_products() if p.get("activo", True)]

    if filtro in TIPOS:
        productos = [p for p in todos if p["tipo"] == filtro]
    elif filtro in CATEGORIAS:
        productos = [p for p in todos if p["categoria"] == filtro]
    else:
        productos = todos

    return render_template("catalog.html", productos=productos,
                           tabs=TABS, filtro_activo=filtro, badges=BADGES, low_stock=LOW_STOCK)


@main_bp.route("/api/related/<tipo>/<int:product_id>")
def api_related(tipo, product_id):
    todos = get_all_products()
    mismos = [p for p in todos if p["tipo"] == tipo and p["id"] != product_id]
    sample = random.sample(mismos, min(4, len(mismos)))
    return jsonify({
        "items": [{
            "id": p["id"], "nombre": p["nombre"], "tipo": p["tipo"],
            "categoria": p["categoria"], "descripcion": p["descripcion"],
            "precio": p["precio"], "emoji": p["emoji"],
            "imagen": p.get("imagen", ""),
            "low_stock": p["id"] in LOW_STOCK,
        } for p in sample]
    })
