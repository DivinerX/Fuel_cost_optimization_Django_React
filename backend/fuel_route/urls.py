from django.urls import path
from . import views

app_name = 'fuel_route'

urlpatterns = [
    path('route/', views.RoutePlanView.as_view(), name='route-plan'),
    path('route/optimize/', views.RouteOptimizeView.as_view(), name='route-optimize'),
    path('route/autocomplete/', views.LocationAutocompleteView.as_view(), name='location-autocomplete'),
]


