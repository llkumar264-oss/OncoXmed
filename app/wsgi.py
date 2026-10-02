"""Production entry point:  gunicorn -w 2 --preload app.wsgi:application"""
from .server import create_app

application = create_app()
