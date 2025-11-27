from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from django.db.models import Avg
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import time
import logging
import math

from .models import FuelStation
from .services import RoutingService, FuelOptimizer
from .serializers import RoutePlanSerializer, RoutePlanResponseSerializer, RouteOptimizeSerializer

logger = logging.getLogger(__name__)


class LocationAutocompleteView(APIView):
    """
    API endpoint for location autocomplete suggestions.
    
    GET /api/route/autocomplete/?q=New York
    Returns a list of location suggestions
    """
    
    def get(self, request):
        query = request.query_params.get('q', '').strip()
        
        if not query or len(query) < 2:
            return Response([], status=status.HTTP_200_OK)
        
        geolocator = Nominatim(user_agent="fuel_optimization_app", timeout=10)

        country_filter = "us"
        
        try:
            # Use geocode with exactly_one=False to get multiple results
            results = geolocator.geocode(
                query,
                exactly_one=False,
                limit=5,
                timeout=10,
                country_codes=country_filter,
            )
            
            suggestions = []
            if results:
                for location in results:
                    suggestions.append({
                        'display_name': location.address,
                        'latitude': location.latitude,
                        'longitude': location.longitude,
                    })
            
            return Response(suggestions, status=status.HTTP_200_OK)
            
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            logger.warning(f"LocationAutocompleteView: Geocoding error: {str(e)}")
            return Response([], status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"LocationAutocompleteView: Unexpected error: {str(e)}")
            return Response([], status=status.HTTP_200_OK)

class RoutePlanView(APIView):
    """
    API endpoint to plan a route with optimal fuel stops.
    
    POST /api/route/
    {
        "start_location": "New York, NY",
        "end_location": "Houston, TX",
        "algorithm": "greedy",
        "initial_fuel_gallons": 20
    }
    """
    
    def post(self, request):
        serializer = RoutePlanSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        initial_context, error_response = self._initial_setup(serializer.validated_data)
        if error_response:
            return error_response
        
        route_context, error_response = self._get_route_data(initial_context)
        if error_response:
            return error_response
        
        fuel_context = self._filter_fuel_stations(
            route_context['optimized_geometry'],
            initial_context['max_distance_km']
        )
        
        optimization_results = self._optimize_fuel_stops(
            fuel_context['optimizer'],
            route_context['optimized_geometry'],
            fuel_context['fuel_stations_list'],
            initial_context,
            route_context['total_distance_miles'],
            fuel_context['fuel_stations_queryset']
        )
        
        response_data = self._build_response_data(
            request,
            initial_context,
            route_context,
            fuel_context,
            optimization_results,
        )
        
        return Response(response_data, status=status.HTTP_200_OK)

    def _initial_setup(self, validated_data):
        start_location = validated_data['start_location']
        end_location = validated_data['end_location']
        max_distance_km = validated_data.get('max_distance_km', 5.0)
        algorithm = validated_data.get('algorithm', 'greedy')
        initial_fuel_gallons = validated_data.get('initial_fuel_gallons', None)
        country_filter = "us"
        
        geolocator = Nominatim(user_agent="fuel_optimization_app", timeout=10)
        
        try:
            start_geo = geolocator.geocode(
                start_location,
                timeout=10,
                country_codes=country_filter,
            )
            if not start_geo:
                return None, Response(
                    {'error': f'Could not geocode start location: {start_location}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            start_lat, start_lon = start_geo.latitude, start_geo.longitude
            
            time.sleep(1)  # Rate limiting
            
            end_geo = geolocator.geocode(
                end_location,
                timeout=10,
                country_codes=country_filter,
            )
            if not end_geo:
                return None, Response(
                    {'error': f'Could not geocode end location: {end_location}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            end_lat, end_lon = end_geo.latitude, end_geo.longitude

            logger.info(
                "RoutePlanView: Geocoded locations - start: %s (%s, %s), end: %s (%s, %s)",
                start_location, start_lat, start_lon, end_location, end_lat, end_lon
            )
            
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            return None, Response(
                {'error': f'Geocoding error: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        return {
            'start_location': start_location,
            'end_location': end_location,
            'max_distance_km': max_distance_km,
            'algorithm': algorithm,
            'initial_fuel_gallons': initial_fuel_gallons,
            'start_lat': start_lat,
            'start_lon': start_lon,
            'end_lat': end_lat,
            'end_lon': end_lon,
        }, None

    def _get_route_data(self, context):
        start_lat = context['start_lat']
        start_lon = context['start_lon']
        end_lat = context['end_lat']
        end_lon = context['end_lon']
        
        logger.info(
            "RoutePlanView: Getting route from (%s, %s) to (%s, %s)",
            start_lat, start_lon, end_lat, end_lon
        )
        
        routing_service = RoutingService()
        route_start_time = time.perf_counter()
        route_data = routing_service.get_route(start_lat, start_lon, end_lat, end_lon)
        route_elapsed = time.perf_counter() - route_start_time
        logger.info(
            "[TIMING] RoutePlanView: get_route from openRouteService API took %.3f seconds",
            route_elapsed
        )
        
        if not route_data:
            return None, Response(
                {'error': 'Could not get route from routing service'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        route_geometry = route_data['geometry']
        total_distance_m = route_data['distance']
        total_distance_km = total_distance_m / 1000
        total_distance_miles = total_distance_km / 1.60934
        
        logger.info(
            "RoutePlanView: Original route has %d points, distance=%.2f km",
            len(route_geometry), total_distance_km
        )
        
        optimize_route = getattr(settings, 'OPTIMIZE_ROUTE_GEOMETRY', True)
        optimized_geometry = route_geometry
        
        optimize_start_time = time.perf_counter()
        if optimize_route and len(route_geometry) > 300:
            logger.info("RoutePlanView: Optimizing route geometry...")
            optimized_geometry = routing_service.optimize_route_geometry(
                route_geometry,
                max_points=getattr(settings, 'OPTIMIZED_ROUTE_MAX_POINTS', 300)
            )
            optimize_elapsed = time.perf_counter() - optimize_start_time
            logger.info(
                "[TIMING] RoutePlanView: Optimizing route took %.3f seconds (reduced from %d to %d points)",
                optimize_elapsed, len(route_geometry), len(optimized_geometry)
            )
        else:
            optimize_elapsed = time.perf_counter() - optimize_start_time
            logger.info(
                "[TIMING] RoutePlanView: Optimizing route took %.3f seconds (skipped, using original %d points)",
                optimize_elapsed, len(route_geometry)
            )
        
        return {
            'routing_service': routing_service,
            'route_geometry': route_geometry,
            'optimized_geometry': optimized_geometry,
            'total_distance_m': total_distance_m,
            'total_distance_km': total_distance_km,
            'total_distance_miles': total_distance_miles,
        }, None

    def _filter_fuel_stations(self, optimized_geometry, max_distance_km):
        route_lats = [pt[1] for pt in optimized_geometry]
        route_lons = [pt[0] for pt in optimized_geometry]
        min_lat, max_lat = min(route_lats), max(route_lats)
        min_lon, max_lon = min(route_lons), max(route_lons)
        
        avg_lat = (min_lat + max_lat) / 2
        lat_deg_threshold = max_distance_km / 111.0
        lon_deg_threshold = max_distance_km / (111.0 * math.cos(math.radians(avg_lat)))
        
        fuel_stations = FuelStation.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False,
            latitude__gte=min_lat - lat_deg_threshold,
            latitude__lte=max_lat + lat_deg_threshold,
            longitude__gte=min_lon - lon_deg_threshold,
            longitude__lte=max_lon + lon_deg_threshold
        )
        
        logger.info(
            "RoutePlanView: Pre-filtered to %d stations in bounding box (within ~%.1f km)",
            fuel_stations.count(), max_distance_km
        )
        
        optimizer = FuelOptimizer(
            vehicle_range_miles=getattr(settings, 'VEHICLE_RANGE_MILES', 500),
            fuel_efficiency_mpg=getattr(settings, 'VEHICLE_FUEL_EFFICIENCY_MPG', 10)
        )
        
        filter_start_time = time.perf_counter()
        nearby_station_ids = set()
        station_distance_info = {}
        stations_processed = 0
        
        for station in fuel_stations:
            stations_processed += 1
            if stations_processed % 100 == 0:
                logger.info(
                    "RoutePlanView: Processed %d/%d stations...",
                    stations_processed, fuel_stations.count()
                )
            
            station_dict = {
                'id': station.id,
                'name': station.truckstop_name,
                'address': f"{station.address}, {station.city}, {station.state}",
                'lat': float(station.latitude),
                'lon': float(station.longitude),
                'price': float(station.retail_price),
            }
            
            result = optimizer.process_station_with_threshold(
                station_dict,
                optimized_geometry,
                max_distance_km=max_distance_km
            )
            
            if result:
                nearby_station_ids.add(station.id)
                station_distance_info[station.id] = {
                    'distance_along_route_km': result.get('distance_along_route_km', 0),
                    'distance_from_route_km': result.get('distance_from_route_km', 0),
                }
        
        if nearby_station_ids:
            fuel_stations = fuel_stations.filter(id__in=nearby_station_ids)
        else:
            logger.info(
                "RoutePlanView: No stations found within %.1f km of route",
                max_distance_km
            )
        
        filter_elapsed = time.perf_counter() - filter_start_time
        logger.info(
            "[TIMING] RoutePlanView: Filtering nearby fuel stops took %.3f seconds (processed %d stations, found %d nearby)",
            filter_elapsed, stations_processed, len(nearby_station_ids)
        )
        
        logger.info(
            "RoutePlanView: Found %d fuel stations within %.1f km of route",
            fuel_stations.count(), max_distance_km
        )
        
        fuel_stations_list = []
        for station in fuel_stations:
            station_dict = {
                'id': station.id,
                'name': station.truckstop_name,
                'address': f"{station.address}, {station.city}, {station.state}",
                'lat': float(station.latitude),
                'lon': float(station.longitude),
                'price': float(station.retail_price),
            }
            if station.id in station_distance_info:
                station_dict['distance_along_route_km'] = station_distance_info[station.id]['distance_along_route_km']
                station_dict['distance_from_route_km'] = station_distance_info[station.id]['distance_from_route_km']
            fuel_stations_list.append(station_dict)
        
        return {
            'fuel_stations_queryset': fuel_stations,
            'station_distance_info': station_distance_info,
            'fuel_stations_list': fuel_stations_list,
            'optimizer': optimizer,
        }

    def _optimize_fuel_stops(
        self,
        optimizer,
        optimized_geometry,
        fuel_stations_list,
        context,
        total_distance_miles,
        fuel_stations_queryset,
    ):
        start_lat = context['start_lat']
        start_lon = context['start_lon']
        end_lat = context['end_lat']
        end_lon = context['end_lon']
        initial_fuel_gallons = context['initial_fuel_gallons']
        algorithm = context['algorithm']
        
        optimal_stops_start_time = time.perf_counter()
        optimal_stops = optimizer.find_optimal_stops(
            optimized_geometry,
            fuel_stations_list,
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            initial_fuel_gallons=initial_fuel_gallons,
            algorithm=algorithm,
        )
        optimal_stops_elapsed = time.perf_counter() - optimal_stops_start_time
        logger.info(
            "[TIMING] RoutePlanView: FuelOptimizer.find_optimal_stops took %.3f seconds (stations_count=%d)",
            optimal_stops_elapsed,
            fuel_stations_queryset.count(),
        )
        
        total_fuel_cost = 0
        total_fuel_gallons_purchased = 0
        
        if optimal_stops:
            total_fuel_cost = sum(stop.get('fuel_cost_at_stop', 0) for stop in optimal_stops)
            total_fuel_gallons_purchased = sum(
                stop.get('fuel_purchased_gallons', 0) for stop in optimal_stops
            )
            
            logger.info(
                f"RoutePlanView: Calculated total_fuel_cost = ${total_fuel_cost:.2f} "
                f"based on actual purchases at {len(optimal_stops)} stops"
            )
            logger.info(
                f"RoutePlanView: Total fuel purchased = {total_fuel_gallons_purchased:.2f} gallons"
            )
            
            if total_fuel_cost == 0:
                logger.warning(
                    "RoutePlanView: fuel_cost_at_stop not available, calculating from price and purchased gallons"
                )
                total_fuel_cost = sum(
                    stop.get('fuel_purchased_gallons', 0) * stop.get('price', 0)
                    for stop in optimal_stops
                )
        else:
            fuel_gallons_needed = total_distance_miles / optimizer.fuel_efficiency_mpg
            avg_price = fuel_stations_queryset.aggregate(
                avg_price=Avg('retail_price')
            )['avg_price'] or 3.50
            total_fuel_cost = fuel_gallons_needed * float(avg_price)
            total_fuel_gallons_purchased = fuel_gallons_needed
        
        return {
            'optimal_stops': optimal_stops,
            'total_fuel_cost': total_fuel_cost,
            'total_fuel_gallons': total_fuel_gallons_purchased,
        }

    def _build_response_data(
        self,
        request,
        initial_context,
        route_context,
        fuel_context,
        optimization_results,
    ):
        start_lat = initial_context['start_lat']
        start_lon = initial_context['start_lon']
        end_lat = initial_context['end_lat']
        end_lon = initial_context['end_lon']
        start_location = initial_context['start_location']
        end_location = initial_context['end_location']
        max_distance_km = initial_context['max_distance_km']
        algorithm = initial_context['algorithm']
        initial_fuel_gallons = initial_context['initial_fuel_gallons']
        optimized_geometry = route_context['optimized_geometry']
        route_geometry = route_context['route_geometry']
        station_distance_info = fuel_context['station_distance_info']
        optimal_stops = optimization_results['optimal_stops']
        total_fuel_cost = optimization_results['total_fuel_cost']
        total_fuel_gallons_purchased = optimization_results['total_fuel_gallons']
        total_distance_km = route_context['total_distance_km']
        total_distance_miles = route_context['total_distance_miles']
        total_distance_m = route_context['total_distance_m']
        
        request.session['start_location'] = start_location
        request.session['end_location'] = end_location
        request.session['start_coords'] = {'latitude': start_lat, 'longitude': start_lon}
        request.session['end_coords'] = {'latitude': end_lat, 'longitude': end_lon}
        
        response_data = {
            'route': {
                'geometry': route_geometry,
                'original_geometry': route_geometry,
                'optimized_geometry': optimized_geometry,
                'total_distance_km': round(total_distance_km, 2),
                'total_distance_miles': round(total_distance_miles, 2),
                'total_distance_meters': round(total_distance_m, 2),
                'original_points_count': len(route_geometry),
                'optimized_points_count': len(optimized_geometry),
            },
            'fuel_stops': [
                {
                    'id': stop.get('id'),
                    'name': stop['name'],
                    'address': stop['address'],
                    'location': {
                        'latitude': stop['lat'],
                        'longitude': stop['lon'],
                    },
                    'price_per_gallon': round(stop['price'], 4),
                    'distance_along_route_km': round(
                        stop.get('distance_along_route_km')
                        or station_distance_info.get(stop.get('id'), {}).get('distance_along_route_km', 0),
                        2,
                    ),
                    'distance_along_route_miles': round(
                        (
                            stop.get('distance_along_route_km')
                            or station_distance_info.get(stop.get('id'), {}).get('distance_along_route_km', 0)
                        ) / 1.60934,
                        2,
                    ),
                    'distance_from_route_km': round(
                        stop.get('distance_from_route_km')
                        or station_distance_info.get(stop.get('id'), {}).get('distance_from_route_km', 0),
                        2,
                    ),
                    'distance_from_route_miles': round(
                        (
                            stop.get('distance_from_route_km')
                            or station_distance_info.get(stop.get('id'), {}).get('distance_from_route_km', 0)
                        ) / 1.60934,
                        2,
                    ),
                    'is_selected': True,
                    'fuel_capacity_at_arrival': stop.get('fuel_capacity_at_arrival', 0),
                    'fuel_purchased_gallons': stop.get('fuel_purchased_gallons', 0),
                    'fuel_cost_at_stop': stop.get('fuel_cost_at_stop', 0),
                }
                for stop in optimal_stops
            ],
            'fuel_stops_count': len(optimal_stops),
            'max_distance_km': max_distance_km,
            'total_fuel_cost': round(total_fuel_cost, 2),
            'total_fuel_gallons': round(total_fuel_gallons_purchased, 2),
            'start_location': start_location,
            'end_location': end_location,
            'start_coords': {'latitude': start_lat, 'longitude': start_lon},
            'end_coords': {'latitude': end_lat, 'longitude': end_lon},
            'algorithm': algorithm,
            'initial_fuel_gallons': initial_fuel_gallons,
        }
        
        return response_data


class RouteOptimizeView(APIView):
    """
    API endpoint to get route from start to end location, optimize it, and filter nearby fuel stops.
    
    POST /api/route/optimize/
    {
        "start_location": "New York, NY",
        "end_location": "Houston, TX",
        "max_distance_km": 5.0  // optional, default 5.0
    }
    """
    
    def post(self, request):
        serializer = RouteOptimizeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        start_location = serializer.validated_data['start_location']
        end_location = serializer.validated_data['end_location']
        max_distance_km = serializer.validated_data.get('max_distance_km', 5.0)
        
        # Geocode locations
        geolocator = Nominatim(user_agent="fuel_optimization_app", timeout=10)
        
        try:
            start_geo = geolocator.geocode(start_location, timeout=10)
            if not start_geo:
                return Response(
                    {'error': f'Could not geocode start location: {start_location}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            start_lat, start_lon = start_geo.latitude, start_geo.longitude
            
            time.sleep(1)  # Rate limiting
            
            end_geo = geolocator.geocode(end_location, timeout=10)
            if not end_geo:
                return Response(
                    {'error': f'Could not geocode end location: {end_location}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            end_lat, end_lon = end_geo.latitude, end_geo.longitude

            logger.info("RouteOptimizeView: Geocoded locations - start: %s (%s, %s), end: %s (%s, %s)", 
                       start_location, start_lat, start_lon, end_location, end_lat, end_lon)
            
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            return Response(
                {'error': f'Geocoding error: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        logger.info("RouteOptimizeView: Getting route from (%s, %s) to (%s, %s)", 
                   start_lat, start_lon, end_lat, end_lon)
        
        # Get route from routing API
        routing_service = RoutingService()
        route_start_time = time.perf_counter()
        route_data = routing_service.get_route(start_lat, start_lon, end_lat, end_lon)
        route_elapsed = time.perf_counter() - route_start_time
        logger.info("[TIMING] RouteOptimizeView: get_route from openRouteService API took %.3f seconds", route_elapsed)
        
        if not route_data:
            return Response(
                {'error': 'Could not get route from routing service'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        route_geometry = route_data['geometry']
        total_distance_m = route_data['distance']
        total_distance_km = total_distance_m / 1000
        total_distance_miles = total_distance_km / 1.60934
        
        logger.info("RouteOptimizeView: Original route has %d points, distance=%.2f km", 
                   len(route_geometry), total_distance_km)
        
        # Optimize route geometry
        optimize_route = getattr(settings, 'OPTIMIZE_ROUTE_GEOMETRY', True)
        optimized_geometry = route_geometry
        
        optimize_start_time = time.perf_counter()
        if optimize_route and len(route_geometry) > 300:
            logger.info("RouteOptimizeView: Optimizing route geometry...")
            optimized_geometry = routing_service.optimize_route_geometry(
                route_geometry,
                max_points=getattr(settings, 'OPTIMIZED_ROUTE_MAX_POINTS', 300)
            )
            optimize_elapsed = time.perf_counter() - optimize_start_time
            logger.info("[TIMING] RouteOptimizeView: Optimizing route took %.3f seconds (reduced from %d to %d points)", 
                       optimize_elapsed, len(route_geometry), len(optimized_geometry))
        else:
            optimize_elapsed = time.perf_counter() - optimize_start_time
            logger.info("[TIMING] RouteOptimizeView: Optimizing route took %.3f seconds (skipped, using original %d points)", 
                       optimize_elapsed, len(route_geometry))
        
        # Pre-filter stations using bounding box to reduce processing
        # Calculate route bounding box
        route_lats = [pt[1] for pt in optimized_geometry]
        route_lons = [pt[0] for pt in optimized_geometry]
        min_lat, max_lat = min(route_lats), max(route_lats)
        min_lon, max_lon = min(route_lons), max(route_lons)
        
        # Expand bounding box by max_distance_km (rough approximation in degrees)
        # ~111 km per degree latitude, ~111*cos(lat) km per degree longitude
        avg_lat = (min_lat + max_lat) / 2
        lat_deg_threshold = max_distance_km / 111.0
        lon_deg_threshold = max_distance_km / (111.0 * math.cos(math.radians(avg_lat)))
        
        # Database-level bounding box filter (much faster than processing all stations)
        fuel_stations = FuelStation.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False,
            latitude__gte=min_lat - lat_deg_threshold,
            latitude__lte=max_lat + lat_deg_threshold,
            longitude__gte=min_lon - lon_deg_threshold,
            longitude__lte=max_lon + lon_deg_threshold
        )
        
        logger.info("RouteOptimizeView: Pre-filtered to %d stations in bounding box (within ~%.1f km)", 
                   fuel_stations.count(), max_distance_km)
        
        # Use FuelOptimizer to find stations near the route
        optimizer = FuelOptimizer()
        
        # Time measurement for filtering nearby fuel stops
        filter_start_time = time.perf_counter()
        
        # Find stations near the route
        nearby_stations = []
        stations_processed = 0
        
        for station in fuel_stations:
            stations_processed += 1
            if stations_processed % 100 == 0:
                logger.info("RouteOptimizeView: Processed %d/%d stations...", 
                           stations_processed, fuel_stations.count())
            
            station_dict = {
                'id': station.id,
                'name': station.truckstop_name,
                'address': f"{station.address}, {station.city}, {station.state}",
                'lat': float(station.latitude),
                'lon': float(station.longitude),
                'price': float(station.retail_price),
            }
            
            # Process station to find distance from route with configurable threshold
            result = optimizer.process_station_with_threshold(station_dict, optimized_geometry, max_distance_km=max_distance_km)
            
            if result:
                nearby_stations.append({
                    'id': result['id'],
                    'name': result['name'],
                    'address': result['address'],
                    'location': {
                        'latitude': result['lat'],
                        'longitude': result['lon'],
                    },
                    'price_per_gallon': round(result['price'], 4),
                    'distance_along_route_km': round(result['distance_along_route_km'], 2),
                    'distance_along_route_miles': round(result['distance_along_route_km'] / 1.60934, 2),
                    'distance_from_route_km': round(result['distance_from_route_km'], 2),
                    'distance_from_route_miles': round(result['distance_from_route_km'] / 1.60934, 2),
                })
        
        # Sort by distance along route
        nearby_stations.sort(key=lambda x: x['distance_along_route_km'])
        
        filter_elapsed = time.perf_counter() - filter_start_time
        logger.info("[TIMING] RouteOptimizeView: Filtering nearby fuel stops took %.3f seconds (processed %d stations, found %d nearby)", 
                   filter_elapsed, stations_processed, len(nearby_stations))
        
        logger.info("RouteOptimizeView: Found %d fuel stations within %.1f km of route", 
                   len(nearby_stations), max_distance_km)
        
        # Format response
        response_data = {
            'route': {
                'original_geometry': route_geometry,
                'optimized_geometry': optimized_geometry,
                'total_distance_km': round(total_distance_km, 2),
                'total_distance_miles': round(total_distance_miles, 2),
                'total_distance_meters': round(total_distance_m, 2),
                'original_points_count': len(route_geometry),
                'optimized_points_count': len(optimized_geometry),
            },
            'fuel_stops': nearby_stations,
            'fuel_stops_count': len(nearby_stations),
            'max_distance_km': max_distance_km,
            'start_location': start_location,
            'end_location': end_location,
            'start_coords': {
                'latitude': start_lat,
                'longitude': start_lon,
            },
            'end_coords': {
                'latitude': end_lat,
                'longitude': end_lon,
            },
        }
        
        return Response(response_data, status=status.HTTP_200_OK)
