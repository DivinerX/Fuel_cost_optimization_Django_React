"""
WSGI config for fuel_optimization project.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fuel_optimization.settings')

application = get_wsgi_application()


