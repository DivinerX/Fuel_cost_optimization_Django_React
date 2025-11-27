from rest_framework import serializers


class RoutePlanSerializer(serializers.Serializer):
    """Serializer for route planning request"""
    start_location = serializers.CharField(
        help_text="Start location (e.g., 'New York, NY' or '40.7128,-74.0060')"
    )
    end_location = serializers.CharField(
        help_text="End location (e.g., 'Los Angeles, CA' or '34.0522,-118.2437')"
    )
    max_distance_km = serializers.FloatField(
        required=False,
        default=5.0,
        help_text="Maximum distance from route to include fuel stops (default: 5.0 km)"
    )
    algorithm = serializers.ChoiceField(
        choices=['greedy', 'dijkstra'],
        required=False,
        default='greedy',
        help_text="Optimization algorithm to use: 'greedy' or 'dijkstra' (default: 'greedy')"
    )
    initial_fuel_gallons = serializers.FloatField(
        required=False,
        default=None,
        allow_null=True,
        min_value=0.0,
        max_value=50.0,
        help_text="Initial fuel level at start in gallons (must be between 0 and 50, default: max fuel capacity)"
    )


class RoutePlanResponseSerializer(serializers.Serializer):
    """Serializer for route planning response"""
    route = serializers.DictField()
    fuel_stops = serializers.ListField()
    total_fuel_cost = serializers.FloatField()
    total_fuel_gallons = serializers.FloatField()


class RouteOptimizeSerializer(serializers.Serializer):
    """Serializer for route optimization request"""
    start_location = serializers.CharField(
        help_text="Start location (e.g., 'New York, NY' or '40.7128,-74.0060')"
    )
    end_location = serializers.CharField(
        help_text="End location (e.g., 'Houston, TX' or '29.7604,-95.3698')"
    )
    max_distance_km = serializers.FloatField(
        required=False,
        default=5.0,
        help_text="Maximum distance from route to include fuel stops (default: 5.0 km)"
    )


