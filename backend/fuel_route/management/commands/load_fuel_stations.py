"""
Management command to load fuel stations from CSV file.
This command geocodes addresses and stores them in the database.
"""
import csv
import os
from django.core.management.base import BaseCommand
from django.conf import settings
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import time

from fuel_route.models import FuelStation


class Command(BaseCommand):
    help = 'Load fuel stations from CSV file and geocode addresses'

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv-file',
            type=str,
            default=None,
            help='Path to CSV file (default: fuel_route/data/fuel-prices.csv)'
        )
        parser.add_argument(
            '--skip-geocoding',
            action='store_true',
            help='Skip geocoding (useful for testing)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Limit number of records to process (for testing)'
        )

    def handle(self, *args, **options):
        csv_file = options.get('csv_file')
        skip_geocoding = options.get('skip_geocoding', False)
        limit = options.get('limit')
        
        if not csv_file:
            # Default to data file in app directory
            csv_file = os.path.join(
                settings.BASE_DIR,
                'fuel_route',
                'data',
                'fuel-prices.csv'
            )
        
        if not os.path.exists(csv_file):
            self.stdout.write(self.style.ERROR(f'CSV file not found: {csv_file}'))
            return
        
        self.stdout.write(f'Loading fuel stations from: {csv_file}')
        
        geolocator = Nominatim(user_agent="fuel_optimization_app", timeout=10)
        processed = 0
        created = 0
        updated = 0
        geocoded = 0
        errors = 0
        
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                if limit and processed >= limit:
                    break
                
                try:
                    opis_id = int(row['OPIS Truckstop ID'])
                    truckstop_name = row['Truckstop Name'].strip()
                    address = row['Address'].strip()
                    city = row['City'].strip()
                    state = row['State'].strip()
                    rack_id = int(row['Rack ID'])
                    retail_price = float(row['Retail Price'])
                    
                    # Get or create station
                    station, created_flag = FuelStation.objects.get_or_create(
                        opis_truckstop_id=opis_id,
                        defaults={
                            'truckstop_name': truckstop_name,
                            'address': address,
                            'city': city,
                            'state': state,
                            'rack_id': rack_id,
                            'retail_price': retail_price,
                        }
                    )
                    
                    if created_flag:
                        created += 1
                    else:
                        # Update existing station
                        station.truckstop_name = truckstop_name
                        station.address = address
                        station.city = city
                        station.state = state
                        station.rack_id = rack_id
                        station.retail_price = retail_price
                        updated += 1
                    
                    # Geocode if needed
                    if not skip_geocoding and (not station.latitude or not station.longitude):
                        location = None
                        
                        # Try multiple address formats
                        address_formats = [
                            f"{truckstop_name}, {city}, {state}, USA",  # Try with business name
                            f"{city}, {state}, USA",  # Fallback to city/state
                            f"{address}, {city}, {state}, USA",  # Original format
                        ]
                        
                        # If address contains highway/interstate info, try extracting it
                        if 'I-' in address or 'US-' in address or 'EXIT' in address.upper():
                            # Try with just city and state (more reliable for highway exits)
                            address_formats.insert(0, f"{city}, {state}, USA")
                            # Try with business name and city/state
                            address_formats.insert(1, f"{truckstop_name}, {city}, {state}, USA")
                        
                        for addr_format in address_formats:
                            try:
                                location = geolocator.geocode(addr_format, timeout=10)
                                if location:
                                    break
                                time.sleep(0.5)  # Small delay between attempts
                            except (GeocoderTimedOut, GeocoderServiceError) as e:
                                self.stdout.write(
                                    self.style.WARNING(
                                        f'Geocoding error for {addr_format}: {e}'
                                    )
                                )
                                time.sleep(1)  # Longer delay on error
                                continue
                        
                        if location:
                            station.latitude = location.latitude
                            station.longitude = location.longitude
                            geocoded += 1
                        else:
                            self.stdout.write(
                                self.style.WARNING(
                                    f'Could not geocode: {truckstop_name}, {city}, {state}'
                                )
                            )
                        
                        # Rate limiting - be nice to geocoding service
                        time.sleep(1)
                    
                    station.save()
                    processed += 1
                    
                    if processed % 100 == 0:
                        self.stdout.write(f'Processed {processed} stations...')
                
                except (ValueError, KeyError) as e:
                    self.stdout.write(
                        self.style.ERROR(f'Error processing row: {e}')
                    )
                    errors += 1
                    continue
        
        self.stdout.write(self.style.SUCCESS(
            f'\nCompleted!\n'
            f'Processed: {processed}\n'
            f'Created: {created}\n'
            f'Updated: {updated}\n'
            f'Geocoded: {geocoded}\n'
            f'Errors: {errors}'
        ))

