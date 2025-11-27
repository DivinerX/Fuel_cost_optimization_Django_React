"""
URL configuration for fuel_optimization project.
API-only backend - no template views.
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('fuel_route.urls')),
]

