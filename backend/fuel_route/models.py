from django.db import models


class FuelStation(models.Model):
    """Model to store fuel station data from CSV"""
    opis_truckstop_id = models.IntegerField(unique=True)
    truckstop_name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    rack_id = models.IntegerField()
    retail_price = models.DecimalField(max_digits=6, decimal_places=4)
    
    # Geocoded location (latitude, longitude)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['state', 'city', 'truckstop_name']
        indexes = [
            models.Index(fields=['latitude', 'longitude']),
            models.Index(fields=['state']),
        ]
    
    def __str__(self):
        return f"{self.truckstop_name} - {self.city}, {self.state}"
