import React, { useEffect, useState, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './RouteMap.css';

// Fix for default marker icons in Leaflet with Webpack
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

function RouteStationsMap() {
  const location = useLocation();
  const navigate = useNavigate();
  const mapRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const markersRef = useRef([]);
  const routePolylineRef = useRef(null);
  const [routeData, setRouteData] = useState(location.state?.routeData || null);

  useEffect(() => {
    // Initialize map
    if (!mapInstanceRef.current && mapRef.current) {
      const map = L.map(mapRef.current).setView([39.8283, -98.5795], 4);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 19,
      }).addTo(map);
      mapInstanceRef.current = map;
    }

    // Draw route and markers if routeData exists
    if (routeData && mapInstanceRef.current) {
      drawRouteAndMarkers(routeData);
    }

    return () => {
      // Cleanup markers and polyline
      markersRef.current.forEach(marker => {
        if (mapInstanceRef.current) {
          mapInstanceRef.current.removeLayer(marker);
        }
      });
      markersRef.current = [];
      
      if (routePolylineRef.current && mapInstanceRef.current) {
        mapInstanceRef.current.removeLayer(routePolylineRef.current);
        routePolylineRef.current = null;
      }
    };
  }, [routeData]);

  const drawRouteAndMarkers = (data) => {
    const map = mapInstanceRef.current;
    if (!map || !data.route) return;

    // Clear existing markers and polyline
    markersRef.current.forEach(marker => map.removeLayer(marker));
    markersRef.current = [];
    
    if (routePolylineRef.current) {
      map.removeLayer(routePolylineRef.current);
      routePolylineRef.current = null;
    }

    // Use original_geometry if available, otherwise fallback to optimized_geometry
    const routeGeometry = data.route.original_geometry || data.route.optimized_geometry || [];
    
    if (routeGeometry.length === 0) return;

    // Convert route geometry to LatLng array (geometry is [lon, lat])
    const routeLatLngs = routeGeometry.map(coord => [coord[1], coord[0]]);

    // Draw route polyline
    const routePolyline = L.polyline(routeLatLngs, {
      color: '#667eea',
      weight: 5,
      opacity: 0.8,
    }).addTo(map);
    routePolylineRef.current = routePolyline;

    // Create custom icons
    const startIcon = L.divIcon({
      className: 'custom-marker',
      html: '<div style="background-color: #8b5cf6; width: 30px; height: 30px; border-radius: 50%; border: 3px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);"></div>',
      iconSize: [30, 30],
      iconAnchor: [15, 15],
    });

    const endIcon = L.divIcon({
      className: 'custom-marker',
      html: '<div style="background-color: #10b981; width: 30px; height: 30px; border-radius: 50%; border: 3px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.3);"></div>',
      iconSize: [30, 30],
      iconAnchor: [15, 15],
    });

    const fuelIcon = L.divIcon({
      className: 'custom-marker',
      html: '<div style="background-color: #3b82f6; width: 18px; height: 18px; border-radius: 50%; border: 2px solid white; box-shadow: 0 2px 4px rgba(0,0,0,0.25);"></div>',
      iconSize: [18, 18],
      iconAnchor: [9, 9],
    });

    // Add start marker
    const startPoint = routeLatLngs[0];
    const startMarker = L.marker(startPoint, { icon: startIcon, zIndexOffset: 1000 }).addTo(map);
    startMarker.bindPopup('<b>📍 Start Location</b>');
    markersRef.current.push(startMarker);

    // Add end marker
    const endPoint = routeLatLngs[routeLatLngs.length - 1];
    const endMarker = L.marker(endPoint, { icon: endIcon, zIndexOffset: 1000 }).addTo(map);
    endMarker.bindPopup('<b>🏁 End Location</b>');
    markersRef.current.push(endMarker);

    // Add fuel stop markers - show all filtered fuel stops
    if (data.fuel_stops && data.fuel_stops.length > 0) {
      data.fuel_stops.forEach((stop, index) => {
        const stopLat = stop.location.latitude;
        const stopLon = stop.location.longitude;

        const fuelMarker = L.marker([stopLat, stopLon], {
          icon: fuelIcon,
          zIndexOffset: 100,
          riseOnHover: true,
        });

        let popupContent = `
          <b>${index + 1}. ${stop.name}</b><br>
          ${stop.address}<br>
        `;

        if (stop.price_per_gallon !== undefined) {
          popupContent += `<b>Price:</b> $${stop.price_per_gallon.toFixed(3)}/gal<br>`;
        }
        if (stop.distance_along_route_miles !== undefined) {
          popupContent += `<b>Distance Along Route:</b> ${stop.distance_along_route_miles.toFixed(1)} miles<br>`;
        }
        if (stop.distance_from_route_miles !== undefined) {
          popupContent += `<b>Distance From Route:</b> ${stop.distance_from_route_miles.toFixed(2)} miles`;
        }

        fuelMarker.bindPopup(popupContent);
        fuelMarker.addTo(map);
        markersRef.current.push(fuelMarker);
      });
    }

    // Fit map to show all markers and route
    const group = new L.featureGroup([
      routePolyline,
      startMarker,
      endMarker,
      ...markersRef.current,
    ]);
    map.fitBounds(group.getBounds().pad(0.1));
  };

  if (!routeData) {
    return (
      <div className="container">
        <div className="header">
          <h1>🗺️ Route & Nearby Stations</h1>
          <button className="back-button" onClick={() => navigate('/')}>
            ← Back to Route Planner
          </button>
        </div>
        <div className="no-route">
          <h2>No Route Data</h2>
          <p>Please plan a route first.</p>
          <button onClick={() => navigate('/')}>Go to Route Planner</button>
        </div>
      </div>
    );
  }

  return (
    <div className="container">
      <div className="header">
        <h1>🗺️ Route & Nearby Stations</h1>
        <button className="back-button" onClick={() => navigate('/')}>
          ← Back to Route Planner
        </button>
      </div>

      <div className="route-summary">
        <div className="summary-grid">
          <div className="summary-item">
            <label>Total Distance</label>
            <div className="value">
              {routeData.route.total_distance_miles.toFixed(1)} mi
            </div>
          </div>
          <div className="summary-item">
            <label>Nearby Fuel Stops</label>
            <div className="value" style={{ color: '#3b82f6', fontWeight: 700 }}>
              {routeData.fuel_stops_count || (routeData.fuel_stops ? routeData.fuel_stops.length : 0)}
            </div>
          </div>
          <div className="summary-item">
            <label>Max Distance</label>
            <div className="value">
              {routeData.max_distance_km ? `${routeData.max_distance_km.toFixed(1)} km` : '5.0 km'}
            </div>
          </div>
          {routeData.route.original_points_count && (
            <div className="summary-item">
              <label>Route Points</label>
              <div className="value">
                {routeData.route.original_points_count.toLocaleString()}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="map-legend">
        <div className="legend-items">
          <div className="legend-item">
            <div className="legend-icon" style={{ backgroundColor: '#8b5cf6' }}></div>
            <span>Start</span>
          </div>
          <div className="legend-item">
            <div className="legend-icon" style={{ backgroundColor: '#10b981' }}></div>
            <span>End</span>
          </div>
          <div className="legend-item">
            <div className="legend-icon" style={{ backgroundColor: '#3b82f6', width: '18px', height: '18px' }}></div>
            <span>Nearby Fuel Stop</span>
          </div>
        </div>
      </div>

      <div className="map-container">
        <div ref={mapRef} id="map"></div>
      </div>
    </div>
  );
}

export default RouteStationsMap;

