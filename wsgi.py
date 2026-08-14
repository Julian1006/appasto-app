import os
import sys

# La carpeta del proyecto debe estar en sys.path para que "import app" funcione
# sin importar desde donde arranque el servidor (gunicorn, systemd, cPanel, etc).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import app

# gunicorn busca "app"; algunos hosts (cPanel/Passenger) buscan "application".
application = app
