import sys
import os

# Reemplazar "TU_USUARIO" con tu username de PythonAnywhere
path = '/home/juanfelipe'
if path not in sys.path:
    sys.path.insert(0, path)

from app import app as application
