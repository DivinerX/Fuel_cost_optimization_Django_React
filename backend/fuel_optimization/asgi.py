"""
ASGI config for fuel_optimization project.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fuel_optimization.settings')

application = get_asgi_application()


