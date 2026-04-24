from flask import Blueprint, render_template, request
from model import get_all_products

main_bp = Blueprint("main", __name__)

TABS = ["Todos", "Res", "Cerdo", "Pollo", "Pescado", "Charcutería", "Lácteos", "Despensa", "Premium", "Especiales", "Económicos", "Huesos"]
TIPOS = ["Res", "Cerdo", "Pollo", "Pescado", "Charcutería", "Lácteos", "Despensa"]
CATEGORIAS = ["Premium", "Especiales", "Económicos", "Huesos"]


@main_bp.route("/")
def index():
    destacados = get_all_products()[:6]
    return render_template("index.html", productos=destacados)


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
                           tabs=TABS, filtro_activo=filtro)
