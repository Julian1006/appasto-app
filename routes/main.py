from flask import Blueprint, render_template, request
from model import get_all_products

main_bp = Blueprint("main", __name__)

TABS = ["Todos", "Res", "Cerdo", "Pollo", "Pescado", "Charcutería", "Lácteos", "Despensa", "Premium", "Especiales", "Económicos", "Huesos"]
TIPOS = ["Res", "Cerdo", "Pollo", "Pescado", "Charcutería", "Lácteos", "Despensa"]
CATEGORIAS = ["Premium", "Especiales", "Económicos", "Huesos"]

DESTACADOS_IDS = [4, 5, 6, 1, 3, 29, 31, 49, 60, 73, 87, 8]

BADGES = {
    1: ('premium', 'Premium'),
    2: ('premium', 'Premium'),
    3: ('premium', 'Premium'),
    4: ('hot', 'Favorito'),
    5: ('hot', 'Favorito'),
    6: ('popular', 'Popular'),
    8: ('popular', 'Popular'),
    14: ('popular', 'Popular'),
    29: ('hot', 'Favorito'),
    31: ('popular', 'Popular'),
}


@main_bp.route("/")
def index():
    todos = get_all_products()
    id_map = {p["id"]: p for p in todos}
    destacados = [id_map[i] for i in DESTACADOS_IDS if i in id_map]
    return render_template("index.html", productos=destacados, badges=BADGES)


@main_bp.route("/nosotros")
def nosotros():
    return render_template("nosotros.html")


@main_bp.route("/catalogo")
def catalogo():
    filtro = request.args.get("filtro", "Todos")
    todos = get_all_products()

    if filtro in TIPOS:
        productos = [p for p in todos if p["tipo"] == filtro]
    elif filtro in CATEGORIAS:
        productos = [p for p in todos if p["categoria"] == filtro]
    else:
        productos = todos

    return render_template("catalog.html", productos=productos,
                           tabs=TABS, filtro_activo=filtro, badges=BADGES)
