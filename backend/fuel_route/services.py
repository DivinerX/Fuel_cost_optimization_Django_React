"""
Services for routing and fuel optimization
"""
import requests
import math
import json
import heapq
from typing import List, Tuple, Dict, Optional
from django.conf import settings
from geopy.distance import geodesic
import polyline

import logging

logger = logging.getLogger(__name__)

# Enable detailed HTTP request/response logging (optional - uncomment to see full HTTP details)
# import urllib3
# urllib3_logger = logging.getLogger('urllib3')
# urllib3_logger.setLevel(logging.DEBUG)
# urllib3_logger.propagate = True

class RoutingService:
    """Service to interact with routing APIs"""
    
    def __init__(self):
        self.provider = getattr(settings, 'ROUTING_API_PROVIDER', 'openrouteservice')
        self.api_key = getattr(settings, 'ROUTING_API_KEY', '')
    
    def get_route(self, start_lat: float, start_lon: float, 
                  end_lat: float, end_lon: float) -> Optional[Dict]:
        """
        Get route from start to end location.
        Returns dict with 'geometry' (list of [lon, lat] coordinates) and 'distance' (meters)
        """
        if self.provider == 'openrouteservice':
            return self._get_route_openrouteservice(start_lat, start_lon, end_lat, end_lon)
        else:
            # Fallback: simple straight-line approximation
            return self._get_route_fallback(start_lat, start_lon, end_lat, end_lon)
    
    def _get_route_openrouteservice(self, start_lat: float, start_lon: float,
                                     end_lat: float, end_lon: float) -> Optional[Dict]:
        """Get route using OpenRouteService API"""
        if not self.api_key:
            logger.error("OpenRouteService API key not configured")
            return None
        
        try:
            logger.info('Fetching route from: (%s, %s) to: (%s, %s)', 
                       start_lat, start_lon, end_lat, end_lon)

            url = f"https://api.openrouteservice.org/v2/directions/driving-car?api_key={self.api_key}"
            headers = {
                'Content-Type': 'application/json',
            }
            body = {
                'coordinates': [
                    [start_lon, start_lat],
                    [end_lon, end_lat]
                ],
                'format': 'geojson'
            }
            
            response = requests.post(url, json=body, headers=headers, timeout=10)
            
            if not response.ok:
                try:
                    error_data = response.json()
                    logger.error('Route API error response: %s', error_data)
                    error_message = error_data.get('error', {}).get('message', 
                                                                    f'Routing failed: {response.status_text}')
                    raise Exception(error_message)
                except ValueError:
                    logger.error('Route API error: %s', response.status_text)
                    raise Exception(f'Routing failed: {response.status_text}')
            
            data = response.json()
            
            # Handle GeoJSON format response (format='geojson')
            if isinstance(data, dict) and data.get('type') == 'FeatureCollection' and data.get('features'):
                feature = data['features'][0]
                if feature.get('geometry') and feature['geometry'].get('type') == 'LineString':
                    geometry = feature['geometry']['coordinates']  # [[lon, lat], ...]
                    
                    # Extract distance from properties if available
                    distance = None
                    if feature.get('properties'):
                        # Try different ways to get distance from GeoJSON response
                        if 'segments' in feature['properties']:
                            segments = feature['properties']['segments']
                            if segments and len(segments) > 0:
                                distance = segments[0].get('distance')  # meters
                        elif 'summary' in feature['properties']:
                            distance = feature['properties']['summary'].get('distance')  # meters
                        elif 'distance' in feature['properties']:
                            distance = feature['properties']['distance']  # meters
                    
                    # If distance not in properties, calculate from geometry
                    if distance is None:
                        total_distance = 0
                        for i in range(len(geometry) - 1):
                            point1 = (geometry[i][1], geometry[i][0])  # (lat, lon)
                            point2 = (geometry[i+1][1], geometry[i+1][0])
                            total_distance += geodesic(point1, point2).meters
                        distance = total_distance
                    
                    return {
                        'geometry': geometry,
                        'distance': distance
                    }
            
            # Handle standard format (routes array) - default format
            if isinstance(data, dict) and 'routes' in data and len(data['routes']) > 0:
                route = data['routes'][0]
                if 'geometry' in route:
                    # Decode polyline if needed
                    if isinstance(route['geometry'], str):
                        # Geometry is encoded polyline, need to decode it
                        try:
                            geometry = polyline.decode(route['geometry'])
                            # Convert from (lat, lon) to [lon, lat]
                            geometry = [[lon, lat] for lat, lon in geometry]
                        except Exception as e:
                            logger.error('Error decoding polyline: %s', e)
                            return None
                    else:
                        geometry = route['geometry']['coordinates']  # [[lon, lat], ...]
                    
                    distance = route.get('summary', {}).get('distance')  # meters
                    
                    return {
                        'geometry': geometry,
                        'distance': distance
                    }
            
            # Log the actual response for debugging
            logger.error('Unexpected response format from OpenRouteService. Response: %s', 
                        str(data)[:500] if data else 'None')
            return None
            
        except requests.exceptions.RequestException as e:
            logger.error('Routing error (request): %s', e)
            return None
        except Exception as e:
            logger.error('Routing error: %s', e)
            return None
    
    def _get_route_fallback(self, start_lat: float, start_lon: float,
                            end_lat: float, end_lon: float) -> Dict:
        """Fallback: create a simple straight-line route with intermediate points"""
        # Calculate distance
        distance_km = geodesic((start_lat, start_lon), (end_lat, end_lon)).kilometers
        distance_m = distance_km * 1000
        
        # Create intermediate points (every ~10km)
        num_points = max(2, int(distance_km / 10) + 1)
        geometry = []
        
        for i in range(num_points):
            ratio = i / (num_points - 1) if num_points > 1 else 0
            lat = start_lat + (end_lat - start_lat) * ratio
            lon = start_lon + (end_lon - start_lon) * ratio
            geometry.append([lon, lat])
        
        return {
            'geometry': geometry,
            'distance': distance_m
        }
    
    def optimize_route_geometry(self, route_geometry: List[List[float]], 
                                max_points: int = 300) -> List[List[float]]:
        """
        Optimize route geometry by reducing the number of points while preserving route shape.
        Uses Douglas-Peucker-like algorithm to keep important waypoints.
        
        Args:
            route_geometry: List of [lon, lat] coordinates
            max_points: Maximum number of points in optimized route (default: 300)
        
        Returns:
            Optimized route geometry with reduced points
        """
        if len(route_geometry) <= max_points:
            return route_geometry
        
        logger.info("Optimizing route geometry: %d points -> %d points", 
                   len(route_geometry), max_points)
        
        # Always keep first and last points
        optimized = [route_geometry[0]]
        
        # Calculate step size to sample points
        step = len(route_geometry) / max_points
        
        # Sample points evenly, but also include points with significant direction changes
        last_idx = 0
        for i in range(1, len(route_geometry) - 1):
            # Always include points at regular intervals
            if i - last_idx >= step:
                optimized.append(route_geometry[i])
                last_idx = i
            # Also include points with significant direction changes
            elif i > 1 and i < len(route_geometry) - 1:
                # Calculate angle change
                p1 = route_geometry[i-1]
                p2 = route_geometry[i]
                p3 = route_geometry[i+1]
                
                # Calculate vectors
                v1_lat = p2[1] - p1[1]
                v1_lon = p2[0] - p1[0]
                v2_lat = p3[1] - p2[1]
                v2_lon = p3[0] - p2[0]
                
                # Calculate angle between vectors (simplified)
                dot = v1_lat * v2_lat + v1_lon * v2_lon
                mag1 = math.sqrt(v1_lat**2 + v1_lon**2)
                mag2 = math.sqrt(v2_lat**2 + v2_lon**2)
                
                if mag1 > 0 and mag2 > 0:
                    cos_angle = dot / (mag1 * mag2)
                    cos_angle = max(-1, min(1, cos_angle))  # Clamp to [-1, 1]
                    angle = math.acos(cos_angle)
                    
                    # Include point if angle change is significant (> 15 degrees)
                    if angle > math.radians(15):
                        if route_geometry[i] not in optimized:
                            optimized.append(route_geometry[i])
                            last_idx = i
        
        # Always keep last point
        if route_geometry[-1] not in optimized:
            optimized.append(route_geometry[-1])
        
        # If still too many points, do uniform sampling
        if len(optimized) > max_points:
            step = len(optimized) / max_points
            final_optimized = [optimized[0]]
            for i in range(1, len(optimized) - 1):
                if int(i * step) > int((i-1) * step):
                    final_optimized.append(optimized[i])
            final_optimized.append(optimized[-1])
            optimized = final_optimized
        
        logger.info("Route optimization complete: %d points (target: %d)", 
                   len(optimized), max_points)
        
        return optimized


class FuelOptimizer:
    """Service to optimize fuel stops along a route"""
    
    # Constants
    MAX_FUEL_CAPACITY_GALLONS = 50.0
    FUEL_EFFICIENCY_MPG = 10.0  # 10 miles per gallon, so 1 gallon = 10 miles
    
    def __init__(self, vehicle_range_miles: float = 500, fuel_efficiency_mpg: float = 10):
        self.vehicle_range_miles = vehicle_range_miles
        self.fuel_efficiency_mpg = fuel_efficiency_mpg
        self.vehicle_range_km = vehicle_range_miles * 1.60934  # Convert to km
    
    def find_optimal_stops(self, route_geometry: List[List[float]], 
                          fuel_stations: List, 
                          start_lat: float = None,
                          start_lon: float = None,
                          end_lat: float = None,
                          end_lon: float = None,
                          initial_fuel_gallons: float = None,
                          algorithm: str = 'greedy') -> List[Dict]:
        """
        Find optimal fuel stops along the route.
        
        Args:
            route_geometry: List of [lon, lat] coordinates along the route
            fuel_stations: QuerySet or list of FuelStation objects
            start_lat: Start latitude
            start_lon: Start longitude
            end_lat: End latitude
            end_lon: End longitude
            initial_fuel_gallons: Initial fuel level at start (gallons)
            algorithm: Optimization algorithm to use ('greedy' or 'dijkstra')
        
        Returns:
            List of dicts with fuel station info and distance along route
        """
        if not route_geometry or len(route_geometry) < 2:
            return []
        
        # Convert fuel_stations to list if it's a QuerySet
        # Check if it's a QuerySet by checking for model attribute (QuerySets have model, lists don't)
        if hasattr(fuel_stations, 'model'):
            # Convert QuerySet to list of dictionaries
            fuel_stations_list = []
            for station in fuel_stations:
                if hasattr(station, 'latitude'):  # It's a FuelStation model instance
                    fuel_stations_list.append({
                        'id': station.id,
                        'name': station.truckstop_name,
                        'address': f"{station.address}, {station.city}, {station.state}",
                        'lat': float(station.latitude),
                        'lon': float(station.longitude),
                        'price': float(station.retail_price),
                    })
                else:  # It's already a dict
                    fuel_stations_list.append(station)
            fuel_stations = fuel_stations_list
        
        if not fuel_stations:
            logger.warning("No fuel stations provided to find_optimal_stops")
            return []
        
        # Get start and end coordinates from route if not provided
        if start_lat is None or start_lon is None:
            start_lat = route_geometry[0][1]  # lat
            start_lon = route_geometry[0][0]  # lon
        
        if end_lat is None or end_lon is None:
            end_lat = route_geometry[-1][1]  # lat
            end_lon = route_geometry[-1][0]  # lon
        
        # Default initial fuel if not provided
        if initial_fuel_gallons is None:
            initial_fuel_gallons = self.MAX_FUEL_CAPACITY_GALLONS
        
        # Calculate total route distance
        total_distance_km = self._calculate_route_distance(route_geometry, len(route_geometry) - 1)
        total_distance_miles = total_distance_km / 1.60934
        logger.info("Total route distance: %.2f km (%.2f miles)", total_distance_km, total_distance_miles)
        
        # Sort by distance along route (if distance_along_route_km is available)
        if fuel_stations and 'distance_along_route_km' in fuel_stations[0]:
            if fuel_stations:
                logger.info("First route station: %s at %.2f km", 
                           fuel_stations[0].get('name', 'unknown'), 
                           fuel_stations[0].get('distance_along_route_km', 0))
            fuel_stations.sort(key=lambda x: x.get('distance_along_route_km', 0))
            logger.info("Sorted %d route stations by distance along route", len(fuel_stations))
        
        # Use selected algorithm
        logger.info("Calling %s algorithm with %d fuel stops...", algorithm, len(fuel_stations))
        # algorithm = 'dijkstra'
        if algorithm == 'greedy':
            return self.greedy_algorithm(
                start_lat, start_lon, end_lat, end_lon,
                initial_fuel_gallons, fuel_stations, total_distance_miles
            )
        elif algorithm == 'dijkstra':
            return self.dijkstra_algorithm(
                start_lat, start_lon, end_lat, end_lon,
                initial_fuel_gallons, fuel_stations, total_distance_miles
            )
        else:
            logger.warning(f"Unknown algorithm: {algorithm}, using greedy")
            return self.greedy_algorithm(
                start_lat, start_lon, end_lat, end_lon,
                initial_fuel_gallons, fuel_stations, total_distance_miles
            )
    
    def greedy_algorithm(self, start_lat: float, start_lon: float,
                        end_lat: float, end_lon: float,
                        initial_fuel_gallons: float,
                        fuel_stops: List[Dict],
                        total_distance_miles: float) -> List[Dict]:
        """
        Greedy algorithm to find optimal fuel stops.
        
        From start point, search fuel stops reachable with current fuel,
        pick the cheapest one. From that stop, refuel to max capacity and repeat.
        
        Args:
            start_lat: Start latitude
            start_lon: Start longitude
            end_lat: End latitude
            end_lon: End longitude
            initial_fuel_gallons: Initial fuel level at start (gallons)
            fuel_stops: List of fuel stops with distance_along_route_km and price
            total_distance_miles: Total distance from start to end in miles
        
        Returns:
            List of selected fuel stops
        """
        if not fuel_stops:
            logger.info("Greedy algorithm: No fuel stops available")
            return []
        
        logger.info("=" * 60)
        logger.info("Starting Greedy Algorithm")
        logger.info(f"Start: ({start_lat:.6f}, {start_lon:.6f})")
        logger.info(f"End: ({end_lat:.6f}, {end_lon:.6f})")
        logger.info(f"Total distance: {total_distance_miles:.2f} miles")
        logger.info(f"Initial fuel: {initial_fuel_gallons:.2f} gallons")
        logger.info(f"Max fuel capacity: {self.MAX_FUEL_CAPACITY_GALLONS:.2f} gallons")
        logger.info(f"Fuel efficiency: {self.FUEL_EFFICIENCY_MPG:.1f} miles/gallon")
        logger.info(f"Total fuel stops available: {len(fuel_stops)}")
        logger.info("=" * 60)
        
        # Current state
        current_fuel_gallons = initial_fuel_gallons
        current_position_miles = 0.0  # Distance from start along route
        optimal_stops = []
        visited_stops = set()  # Track visited stops to avoid duplicates
        iteration = 0
        
        # Calculate distance to end
        end_distance_miles = total_distance_miles
        
        while current_position_miles < end_distance_miles:
            iteration += 1
            logger.info("-" * 60)
            logger.info(f"Iteration {iteration}: Current position = {current_position_miles:.2f} miles")
            logger.info(f"Current fuel: {current_fuel_gallons:.2f} gallons")
            
            # Calculate how far we can go with current fuel (in miles)
            current_range_miles = current_fuel_gallons * self.FUEL_EFFICIENCY_MPG
            logger.info(f"Current range: {current_range_miles:.2f} miles")
            
            # Check if we can reach the end with current fuel
            remaining_distance_miles = end_distance_miles - current_position_miles
            logger.info(f"Remaining distance to end: {remaining_distance_miles:.2f} miles")
            
            if remaining_distance_miles <= current_range_miles:
                # We can reach the end, no need for more stops
                logger.info("✓ Can reach end with current fuel. No more stops needed.")
                break
            
            logger.info(f"Need to refuel. Searching for reachable fuel stops within {current_range_miles:.2f} miles...")
            
            # Find all reachable fuel stops from current position
            reachable_stops = []
            for stop in fuel_stops:
                stop_distance_miles = stop['distance_along_route_km'] / 1.60934
                distance_to_stop_miles = stop_distance_miles - current_position_miles
                
                # Check if stop is ahead of us and within range
                if (distance_to_stop_miles > 0 and 
                    distance_to_stop_miles <= current_range_miles and
                    stop['id'] not in visited_stops):
                    reachable_stops.append({
                        **stop,
                        'distance_to_stop_miles': distance_to_stop_miles
                    })
            
            logger.info(f"Found {len(reachable_stops)} reachable fuel stop(s)")
            
            if not reachable_stops:
                # No reachable stops - check if we can still reach end
                if remaining_distance_miles > current_range_miles:
                    logger.warning(f"⚠ Cannot reach end ({remaining_distance_miles:.2f} miles) or any fuel stop from current position")
                    logger.warning(f"Current range is only {current_range_miles:.2f} miles")
                    break
                logger.info("No reachable stops, but can reach end")
                break
            
            # Log all reachable stops
            for stop in reachable_stops:
                logger.info(f"  - {stop['name']}: {stop['distance_to_stop_miles']:.2f} miles away, "
                           f"price: ${stop['price']:.4f}/gallon")
            
            # Pick the cheapest reachable stop
            cheapest_stop = min(reachable_stops, key=lambda x: x['price'])
            
            logger.info(f"→ Selected cheapest stop: {cheapest_stop['name']}")
            logger.info(f"  Distance: {cheapest_stop['distance_to_stop_miles']:.2f} miles")
            logger.info(f"  Price: ${cheapest_stop['price']:.4f}/gallon")
            
            # Calculate fuel consumed to reach this stop
            distance_to_stop_miles = cheapest_stop['distance_to_stop_miles']
            fuel_consumed = distance_to_stop_miles / self.FUEL_EFFICIENCY_MPG
            logger.info(f"  Fuel consumed to reach stop: {fuel_consumed:.2f} gallons")
            
            current_fuel_gallons -= fuel_consumed
            fuel_capacity_at_arrival = current_fuel_gallons  # Fuel level when arriving at stop
            logger.info(f"  Fuel remaining after travel: {current_fuel_gallons:.2f} gallons")
            
            # Update current position to this stop
            stop_position_miles = cheapest_stop['distance_along_route_km'] / 1.60934
            remaining_distance_to_end = end_distance_miles - stop_position_miles
            
            # Calculate minimum fuel needed to reach the end from this stop
            min_fuel_needed_gallons = remaining_distance_to_end / self.FUEL_EFFICIENCY_MPG
            
            # Check if this is the last stop (we can reach end after refueling here)
            # Only refuel enough to reach the end, not to max capacity
            if remaining_distance_to_end <= (self.MAX_FUEL_CAPACITY_GALLONS * self.FUEL_EFFICIENCY_MPG):
                # This is the last stop - only refuel enough to reach the end
                fuel_needed = min_fuel_needed_gallons - current_fuel_gallons
                
                # If we already have enough fuel, add a small safety buffer
                if fuel_needed <= 0:
                    fuel_added = 0.1  # Small buffer for safety
                    logger.info(f"  Already have enough fuel to reach end, adding safety buffer: +{fuel_added:.2f} gallons")
                else:
                    # Calculate how much to refuel, but don't exceed max capacity
                    fuel_added = min(fuel_needed, self.MAX_FUEL_CAPACITY_GALLONS - current_fuel_gallons)
                    # Add a small buffer (5% or 0.1 gallons, whichever is larger) for safety
                    safety_buffer = max(0.1, fuel_added * 0.05)
                    fuel_added += safety_buffer
                    # Don't exceed max capacity
                    fuel_added = min(fuel_added, self.MAX_FUEL_CAPACITY_GALLONS - current_fuel_gallons)
                
                current_fuel_gallons += fuel_added
                fuel_cost_at_stop = fuel_added * cheapest_stop['price']
                logger.info(f"  Last stop before end - refueled only what's needed: +{fuel_added:.2f} gallons → {current_fuel_gallons:.2f} gallons")
                logger.info(f"  Remaining distance to end: {remaining_distance_to_end:.2f} miles (needs {min_fuel_needed_gallons:.2f} gallons)")
            else:
                # Not the last stop - refuel to max capacity
                fuel_added = self.MAX_FUEL_CAPACITY_GALLONS - current_fuel_gallons
                fuel_cost_at_stop = fuel_added * cheapest_stop['price']  # Cost for this refuel
                current_fuel_gallons = self.MAX_FUEL_CAPACITY_GALLONS
                logger.info(f"  Refueled to max capacity: +{fuel_added:.2f} gallons → {current_fuel_gallons:.2f} gallons")
            
            logger.info(f"  Fuel cost at this stop: ${fuel_cost_at_stop:.2f}")
            
            # Add fuel information to the stop before adding to optimal_stops
            cheapest_stop['fuel_capacity_at_arrival'] = round(fuel_capacity_at_arrival, 2)
            cheapest_stop['fuel_purchased_gallons'] = round(fuel_added, 2)
            cheapest_stop['fuel_cost_at_stop'] = round(fuel_cost_at_stop, 2)
            
            # Add to optimal stops
            optimal_stops.append(cheapest_stop)
            visited_stops.add(cheapest_stop['id'])
            
            # Update current position (using already calculated stop_position_miles)
            current_position_miles = stop_position_miles
            logger.info(f"  New position: {current_position_miles:.2f} miles from start")
        
        logger.info("=" * 60)
        logger.info("Greedy Algorithm Complete")
        logger.info(f"Total stops selected: {len(optimal_stops)}")
        logger.info(f"Final position: {current_position_miles:.2f} miles")
        logger.info(f"Remaining distance to end: {end_distance_miles - current_position_miles:.2f} miles")
        if optimal_stops:
            # Calculate actual total cost and fuel purchased
            total_cost = sum(stop.get('fuel_cost_at_stop', 0) for stop in optimal_stops)
            total_fuel_purchased = sum(stop.get('fuel_purchased_gallons', 0) for stop in optimal_stops)
            
            # Fallback if fuel_cost_at_stop not available
            if total_cost == 0:
                total_cost = sum(stop.get('fuel_purchased_gallons', 0) * stop.get('price', 0) for stop in optimal_stops)
            
            logger.info(f"Total fuel purchased: {total_fuel_purchased:.2f} gallons")
            logger.info(f"Total fuel cost: ${total_cost:.2f}")
        logger.info("=" * 60)
        
        return optimal_stops
    
    def dijkstra_algorithm(self, start_lat: float, start_lon: float,
                        end_lat: float, end_lon: float,
                        initial_fuel_gallons: float,
                        fuel_stops: List[Dict],
                        total_distance_miles: float) -> List[Dict]:
        """
        Dijkstra algorithm to find optimal fuel stops.
        
        Uses Dijkstra's algorithm to find the minimum cost path by exploring
        states of (station_index, fuel_in_tank) and choosing optimal fuel purchases.
        
        Args:
            start_lat: Start latitude
            start_lon: Start longitude
            end_lat: End latitude
            end_lon: End longitude
            initial_fuel_gallons: Initial fuel level at start (gallons)
            fuel_stops: List of fuel stops with distance_along_route_km and price
            total_distance_miles: Total distance from start to end in miles
        
        Returns:
            List of selected fuel stops with fuel purchase information
        """
        if not fuel_stops:
            logger.info("Dijkstra algorithm: No fuel stops available")
            return []
        
        logger.info("=" * 60)
        logger.info("Starting Dijkstra Algorithm")
        logger.info(f"Start: ({start_lat:.6f}, {start_lon:.6f})")
        logger.info(f"End: ({end_lat:.6f}, {end_lon:.6f})")
        logger.info(f"Total distance: {total_distance_miles:.2f} miles")
        logger.info(f"Initial fuel: {initial_fuel_gallons:.2f} gallons")
        logger.info(f"Max fuel capacity: {self.MAX_FUEL_CAPACITY_GALLONS:.2f} gallons")
        logger.info(f"Fuel efficiency: {self.FUEL_EFFICIENCY_MPG:.1f} miles/gallon")
        logger.info(f"Total fuel stops available: {len(fuel_stops)}")
        logger.info("=" * 60)
        
        # Convert fuel stops to miles and prepare stations list
        # Add start position as station 0 (distance 0, cannot buy fuel here)
        stations = [{
            'distance': 0.0,
            'price': float('inf'),  # Cannot buy fuel at start
            'original_stop': None
        }]
        
        # Add actual fuel stops
        for stop in fuel_stops:
            distance_miles = stop['distance_along_route_km'] / 1.60934
            stations.append({
                'distance': distance_miles,
                'price': stop['price'],
                'original_stop': stop  # Keep reference to original stop data
            })
        
        # Add destination as last "station" with infinite price
        stations.append({
            'distance': total_distance_miles,
            'price': float('inf'),
            'original_stop': None
        })
        
        n = len(stations)
        mpg = self.FUEL_EFFICIENCY_MPG
        fuel_step = 0.02

        def gallons_to_steps(gallons: float, round_up: bool = False) -> int:
            scaled = gallons / fuel_step
            if round_up:
                return int(math.ceil(scaled - 1e-9))
            return int(round(scaled))

        def steps_to_gallons(steps: int) -> float:
            return steps * fuel_step

        tank_capacity_gallons = self.MAX_FUEL_CAPACITY_GALLONS
        tank_capacity_steps = gallons_to_steps(tank_capacity_gallons)
        initial_fuel_steps = min(
            gallons_to_steps(min(initial_fuel_gallons, tank_capacity_gallons)),
            tank_capacity_steps,
        )
        max_range_miles = tank_capacity_gallons * mpg
        
        # Ensure route is monotonically increasing in distance and reachable
        for idx in range(1, n):
            segment = stations[idx]['distance'] - stations[idx - 1]['distance']
            if segment < -1e-6:
                logger.warning("Route stations are not sorted by distance")
                return []
            if segment - 1e-6 > max_range_miles:
                logger.warning(
                    "Gap between stations exceeds maximum driving range; route unreachable"
                )
                return []
        
        # Sliding window: furthest station reachable from each station
        reachable_end = [i for i in range(n)]
        right = 0
        for i in range(n):
            if right < i:
                right = i
            while (
                right + 1 < n
                and stations[right + 1]['distance'] - stations[i]['distance']
                <= max_range_miles + 1e-6
            ):
                right += 1
            reachable_end[i] = right
        
        # Next cheaper station using monotonic stack
        next_cheaper = [-1] * n
        price_stack = []
        for idx in range(n - 1, -1, -1):
            price = stations[idx]['price']
            while price_stack and price <= stations[price_stack[-1]]['price']:
                price_stack.pop()
            next_cheaper[idx] = price_stack[-1] if price_stack else -1
            if price < float('inf'):
                price_stack.append(idx)
        
        # Sparse edges limited to reachable / useful stations
        edges = [[] for _ in range(n)]
        edge_lookup = {}
        
        def register_edge(src_idx: int, dst_idx: int):
            if dst_idx <= src_idx:
                return
            dist = stations[dst_idx]['distance'] - stations[src_idx]['distance']
            if dist < -1e-6 or dist > max_range_miles + 1e-6:
                return
            gallons = dist / mpg
            if gallons > tank_capacity_gallons + 1e-6:
                return
            needed_steps = gallons_to_steps(gallons, round_up=True)
            edges[src_idx].append((dst_idx, needed_steps))
            edge_lookup[(src_idx, dst_idx)] = needed_steps
        
        for i in range(n - 1):
            max_idx = reachable_end[i]
            if max_idx <= i:
                continue
            candidates = set()
            if i + 1 <= max_idx:
                candidates.add(i + 1)
            cheaper_idx = next_cheaper[i]
            if cheaper_idx != -1 and cheaper_idx <= max_idx:
                candidates.add(cheaper_idx)
            candidates.add(max_idx)
            if reachable_end[i] >= n - 1:
                candidates.add(n - 1)
            for candidate in candidates:
                register_edge(i, candidate)
        
        for i in range(n - 1):
            if not edges[i]:
                logger.warning(
                    f"No reachable stations from index {i}; cannot complete route"
                )
                return []

        def get_fuel_needed_steps(src_idx: int, dst_idx: int) -> int:
            if src_idx == dst_idx:
                return 0
            if (src_idx, dst_idx) in edge_lookup:
                return edge_lookup[(src_idx, dst_idx)]
            dist = stations[dst_idx]['distance'] - stations[src_idx]['distance']
            gallons = dist / mpg
            needed_steps = gallons_to_steps(gallons, round_up=True)
            edge_lookup[(src_idx, dst_idx)] = needed_steps
            return needed_steps
        
        # Dijkstra state: (cost, station_index, fuel_in_tank)
        pq = []
        heapq.heappush(pq, (0.0, 0, initial_fuel_steps))
        
        # best cost seen for (station_index, fuel_in_tank)
        best = [[float('inf')] * (tank_capacity_steps + 1) for _ in range(n)]
        best[0][initial_fuel_steps] = 0.0
        
        # for reconstruction: parent[(station_index, fuel)] = (prev_station_index, prev_fuel, fuel_purchased)
        parent = {(0, initial_fuel_steps): None}
        while pq:
            cost, i, f = heapq.heappop(pq)
            
            if cost != best[i][f]:
                continue
            
            # If at destination, reconstruct path
            if i == n - 1:
                # Reconstruct path
                plan = []
                cur = (i, f)
                while cur:
                    plan.append(cur)
                    cur = parent.get(cur)
                plan.reverse()
                
                # Convert path to fuel stops format
                optimal_stops = []
                total_cost = cost
                
                # Process the path to extract fuel purchases
                # Track stations we've visited and their purchase info
                station_info = {}  # station_idx -> {'arrival_fuel': float, 'fuel_purchased': float, 'original_stop': dict}
                
                for idx in range(len(plan) - 1):  # -1 to skip destination
                    curr_station, curr_fuel = plan[idx]
                    next_station, next_fuel = plan[idx + 1]
                    
                    # Skip start position (station 0) and destination (station n-1)
                    if curr_station == 0 or curr_station == n - 1:
                        # But track arrival at next station if we're driving
                        if curr_station == 0 and next_station != n - 1:
                            fuel_consumed = get_fuel_needed_steps(curr_station, next_station)
                            fuel_at_arrival = curr_fuel - fuel_consumed
                            if next_station not in station_info:
                                original_stop = stations[next_station]['original_stop']
                                if original_stop:
                                    station_info[next_station] = {
                                        'arrival_fuel': steps_to_gallons(fuel_at_arrival),
                                        'fuel_purchased': 0.0,
                                        'original_stop': original_stop
                                    }
                        continue
                    
                    # Get the original stop
                    original_stop = stations[curr_station]['original_stop']
                    if original_stop is None:
                        continue
                    
                    if curr_station == next_station:
                        # Same station, fuel increased = fuel purchase
                        if curr_station not in station_info:
                            # First time at this station in this iteration
                            station_info[curr_station] = {
                                'arrival_fuel': steps_to_gallons(curr_fuel),
                                'fuel_purchased': 0.0,
                                'original_stop': original_stop
                            }
                        
                        fuel_bought_steps = next_fuel - curr_fuel
                        if fuel_bought_steps > 0:
                            station_info[curr_station]['fuel_purchased'] += steps_to_gallons(fuel_bought_steps)
                    else:
                        # Drove to a different station
                        # First, finalize current station if we made purchases
                        if curr_station in station_info and station_info[curr_station]['fuel_purchased'] > 0:
                            info = station_info[curr_station]
                            fuel_cost = info['fuel_purchased'] * stations[curr_station]['price']
                            info['original_stop']['fuel_capacity_at_arrival'] = round(info['arrival_fuel'], 2)
                            info['original_stop']['fuel_purchased_gallons'] = round(info['fuel_purchased'], 2)
                            info['original_stop']['fuel_cost_at_stop'] = round(fuel_cost, 2)
                            optimal_stops.append(info['original_stop'])
                            del station_info[curr_station]
                        
                        # Track arrival at next station
                        if next_station != n - 1:  # Not destination
                            fuel_consumed = get_fuel_needed_steps(curr_station, next_station)
                            fuel_at_arrival = curr_fuel - fuel_consumed
                            if next_station not in station_info:
                                next_original_stop = stations[next_station]['original_stop']
                                if next_original_stop:
                                    station_info[next_station] = {
                                        'arrival_fuel': steps_to_gallons(fuel_at_arrival),
                                        'fuel_purchased': 0.0,
                                        'original_stop': next_original_stop
                                    }
                
                # Handle any remaining stations (e.g., last station before destination)
                for station_idx, info in station_info.items():
                    if info['fuel_purchased'] > 0:
                        fuel_cost = info['fuel_purchased'] * stations[station_idx]['price']
                        info['original_stop']['fuel_capacity_at_arrival'] = round(info['arrival_fuel'], 2)
                        info['original_stop']['fuel_purchased_gallons'] = round(info['fuel_purchased'], 2)
                        info['original_stop']['fuel_cost_at_stop'] = round(fuel_cost, 2)
                        optimal_stops.append(info['original_stop'])
                
                logger.info("=" * 60)
                logger.info("Dijkstra Algorithm Complete")
                logger.info(f"Total stops selected: {len(optimal_stops)}")
                logger.info(f"Total cost: ${total_cost:.2f}")
                if optimal_stops:
                    total_fuel_purchased = sum(stop.get('fuel_purchased_gallons', 0) for stop in optimal_stops)
                    logger.info(f"Total fuel purchased: {total_fuel_purchased:.2f} gallons")
                logger.info("=" * 60)
                
                return optimal_stops
            
            # Option 1: BUY FUEL (if tank not full)
            if f < tank_capacity_steps:
                next_f = f + 1
                next_cost = cost + stations[i]['price'] * fuel_step
                
                if next_cost < best[i][next_f]:
                    best[i][next_f] = next_cost
                    heapq.heappush(pq, (next_cost, i, next_f))
                    parent[(i, next_f)] = (i, f)
            
            # Option 2: DRIVE TO RELEVANT NEXT STATIONS
            for j, needed in edges[i]:
                if needed <= f:  # fuel is enough
                    next_f = int(f - needed)
                    next_cost = cost
                    
                    if next_cost < best[j][next_f]:
                        best[j][next_f] = next_cost
                        heapq.heappush(pq, (next_cost, j, next_f))
                        parent[(j, next_f)] = (i, f)
        
        logger.warning("Dijkstra algorithm: Could not reach destination")
        return []
    
    def _point_to_segment_distance(self, px: float, py: float,
                                    x1: float, y1: float, x2: float, y2: float) -> float:
        """Calculate distance from point to line segment using geodesic distance"""
        # Convert to (lat, lon) tuples for geopy
        A = (y1, x1)  # (lat, lon)
        B = (y2, x2)  # (lat, lon)
        P = (py, px)  # (lat, lon)
        
        # If segment is a point, return distance to that point
        if x1 == x2 and y1 == y2:
            return geodesic(P, A).kilometers
        
        # Calculate distances to endpoints first (cheapest check)
        dist_to_A = geodesic(P, A).kilometers
        dist_to_B = geodesic(P, B).kilometers
        min_dist = min(dist_to_A, dist_to_B)
        
        # Early exit if already very close (optimization)
        if min_dist < 0.1:  # Within 100m
            return min_dist
        
        # Segment length
        segment_length = geodesic(A, B).kilometers
        if segment_length == 0:
            return dist_to_A
        
        # For longer segments, sample fewer points to reduce geodesic calls
        # Use adaptive sampling based on segment length
        if segment_length < 1.0:  # Short segment (< 1km)
            num_samples = 3
        elif segment_length < 5.0:  # Medium segment (< 5km)
            num_samples = 5
        else:  # Long segment
            num_samples = 7
        
        # Sample points along the segment
        for i in range(1, num_samples):  # Skip endpoints (already checked)
            ratio = i / num_samples
            # Interpolate point along segment
            sample_lat = y1 + (y2 - y1) * ratio
            sample_lon = x1 + (x2 - x1) * ratio
            sample_point = (sample_lat, sample_lon)
            
            dist = geodesic(P, sample_point).kilometers
            min_dist = min(min_dist, dist)
            
            # Early exit if we found a very close point
            if min_dist < 0.1:
                break
        
        return min_dist
    
    def _calculate_route_distance(self, route_geometry: List[List[float]], 
                                  end_idx: int) -> float:
        """Calculate cumulative distance along route up to end_idx"""
        total_km = 0
        for i in range(end_idx):
            if i + 1 < len(route_geometry):
                point1 = (route_geometry[i][1], route_geometry[i][0])  # (lat, lon)
                point2 = (route_geometry[i+1][1], route_geometry[i+1][0])
                total_km += geodesic(point1, point2).kilometers
        return total_km
    
    def _fast_point_to_segment_distance_km(self, px: float, py: float,
                                           x1: float, y1: float, x2: float, y2: float) -> float:
        """
        Fast planar distance calculation (much faster than geodesic).
        Uses equirectangular projection approximation.
        Returns distance in kilometers.
        """
        # Convert lat/lon to approximate km using equirectangular projection
        lat_rad = math.radians(py)
        lat_scale = 111.0  # km per degree latitude
        lon_scale = 111.0 * math.cos(lat_rad)  # km per degree longitude at this latitude
        
        # Convert points to km space
        Px = (px - x1) * lon_scale
        Py = (py - y1) * lat_scale
        Ax = 0.0
        Ay = 0.0
        Bx = (x2 - x1) * lon_scale
        By = (y2 - y1) * lat_scale
        
        # Vector from A to B
        ABx = Bx - Ax
        ABy = By - Ay
        
        # Segment length squared
        seg_len_sq = ABx * ABx + ABy * ABy
        
        if seg_len_sq == 0.0:
            # Segment is a point
            return math.sqrt(Px * Px + Py * Py)
        
        # Project P onto segment AB
        dot = Px * ABx + Py * ABy
        t = dot / seg_len_sq
        
        if t <= 0.0:
            # Closest to A
            return math.sqrt(Px * Px + Py * Py)
        elif t >= 1.0:
            # Closest to B
            Cx = Px - Bx
            Cy = Py - By
            return math.sqrt(Cx * Cx + Cy * Cy)
        else:
            # Closest point is interior to the segment
            Cx = Px - (Ax + t * ABx)
            Cy = Py - (Ay + t * ABy)
            return math.sqrt(Cx * Cx + Cy * Cy)
    
    def process_station_with_threshold(self, station: Dict, route_geometry: List[List[float]], 
                                       max_distance_km: float = 5.0) -> Optional[Dict]:
        """
        Process a single station to find its distance from the route.
        Returns the station dict with distance info if within threshold, None otherwise.
        Uses fast planar calculations for speed.
        
        Args:
            station: Dict with 'lat', 'lon', and other station info
            route_geometry: List of [lon, lat] coordinates along the route
            max_distance_km: Maximum distance from route in km (default: 5.0)
        
        Returns:
            Station dict with added 'distance_from_route_km' and 'distance_along_route_km',
            or None if station is too far from route
        """
        if not route_geometry or len(route_geometry) < 2:
            return None
        
        station_lat = station['lat']
        station_lon = station['lon']
        
        # Fast bounding box check first - eliminate obviously far stations
        route_lats = [pt[1] for pt in route_geometry]
        route_lons = [pt[0] for pt in route_geometry]
        min_lat, max_lat = min(route_lats), max(route_lats)
        min_lon, max_lon = min(route_lons), max(route_lons)
        
        # Expand bounding box by max_distance_km (rough approximation in degrees)
        # ~111 km per degree latitude, ~111*cos(lat) km per degree longitude
        avg_lat = (min_lat + max_lat) / 2
        lat_deg_threshold = max_distance_km / 111.0
        lon_deg_threshold = max_distance_km / (111.0 * math.cos(math.radians(avg_lat)))
        
        if (station_lat < min_lat - lat_deg_threshold or 
            station_lat > max_lat + lat_deg_threshold or
            station_lon < min_lon - lon_deg_threshold or
            station_lon > max_lon + lon_deg_threshold):
            # Station is definitely too far
            return None
        
        # Find closest point on route using fast planar calculations
        min_dist = float('inf')
        closest_idx = 0
        
        # Adaptive sampling based on route length
        # For optimized_geometry (typically 300-500 points), check all segments
        num_segments = len(route_geometry) - 1
        if num_segments > 1000:
            # For very long routes, sample more aggressively
            step = max(1, num_segments // 1000)  # Sample ~1000 segments max
        elif num_segments > 500:
            step = max(1, num_segments // 500)  # Sample ~500 segments
        else:
            step = 1  # Check all segments for shorter/optimized routes
        
        logger.debug("process_station_with_threshold: Checking station %s against %d segments (step=%d)", 
                    station.get('name', 'unknown'), num_segments, step)
        
        for i in range(0, num_segments, step):
            if i + 1 >= len(route_geometry):
                break
            
            # Fast planar distance calculation
            dist = self._fast_point_to_segment_distance_km(
                station_lon, station_lat,
                route_geometry[i][0], route_geometry[i][1],
                route_geometry[i+1][0], route_geometry[i+1][1]
            )
            
            if dist < min_dist:
                min_dist = dist
                closest_idx = i
            
            # Early exit if we found a very close station (optimization)
            if min_dist < 0.05:  # Within 50m, good enough
                break
        
        # Only include stations within threshold (check after examining all segments)
        if min_dist > max_distance_km:
            logger.debug("process_station_with_threshold: Station %s is too far (%.2f km > %.2f km)", 
                        station.get('name', 'unknown'), min_dist, max_distance_km)
            return None
        
        # Calculate distance along route to this point
        route_distance = self._calculate_route_distance(route_geometry, closest_idx)
        
        logger.debug("process_station_with_threshold: Station %s is within threshold (%.2f km <= %.2f km)", 
                    station.get('name', 'unknown'), min_dist, max_distance_km)
        
        # Return station with distance info
        return {
            **station,
            'distance_along_route_km': route_distance,
            'distance_from_route_km': min_dist,
        }
    
    def _find_best_station_in_range(self, stations: List[Dict], 
                                    start_distance: float, 
                                    max_range: float) -> Optional[Dict]:
        """Find the cheapest station within range"""
        candidates = [
            s for s in stations
            if start_distance <= s['distance_along_route_km'] <= start_distance + max_range
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda x: x['price'])

