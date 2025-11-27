from django.contrib import admin
from .models import FuelStation


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ('truckstop_name', 'city', 'state', 'retail_price', 'latitude', 'longitude')
    list_filter = ('state',)
    search_fields = ('truckstop_name', 'city', 'address')
    readonly_fields = ('created_at', 'updated_at')
