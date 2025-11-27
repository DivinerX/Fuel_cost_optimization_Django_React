import React, { useEffect, useState, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './RouteMap.css';

// const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

// Fix for default marker icons in Leaflet with Webpack
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

function RouteMap() {
  const location = useLocation();
  const navigate = useNavigate();
  const mapRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const markersRef = useRef([]);
  const [routeData, setRouteData] = useState(location.state?.routeData || null);
  const [showAllStops, setShowAllStops] = useState(false);

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
      // Cleanup markers
      markersRef.current.forEach(marker => {
        if (mapInstanceRef.current) {
          mapInstanceRef.current.removeLayer(marker);
        }
      });
      markersRef.current = [];
    };
  }, [routeData, showAllStops]);

  const drawRouteAndMarkers = (data) => {
    const map = mapInstanceRef.current;
    if (!map || !data.route || !data.route.geometry) return;

    // Clear existing markers
    markersRef.current.forEach(marker => map.removeLayer(marker));
    markersRef.current = [];

    const routeGeometry = data.route.geometry;

    // Convert route geometry to LatLng array
    const routeLatLngs = routeGeometry.map(coord => [coord[1], coord[0]]);

    // Draw route polyline
    const routePolyline = L.polyline(routeLatLngs, {
      color: '#667eea',
      weight: 5,
      opacity: 0.8,
    }).addTo(map);

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

    const selectedFuelIcon = L.divIcon({
      className: 'custom-marker',
      html: '<div style="background-color: #8b4513; width: 22px; height: 22px; border-radius: 50%; border: 3px solid white; box-shadow: 0 2px 6px rgba(0,0,0,0.4);"></div>',
      iconSize: [22, 22],
      iconAnchor: [11, 11],
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

    // Add fuel stop markers
    if (data.fuel_stops && data.fuel_stops.length > 0) {
      data.fuel_stops.forEach((stop, index) => {
        const stopLat = stop.location.latitude;
        const stopLon = stop.location.longitude;
        const isSelected = stop.is_selected === true;

        // Only show selected stops by default, or all if checkbox is checked
        if (isSelected || showAllStops) {
          const iconToUse = isSelected ? selectedFuelIcon : fuelIcon;
          const zIndex = isSelected ? 2000 : 100;

          const fuelMarker = L.marker([stopLat, stopLon], {
            icon: iconToUse,
            zIndexOffset: zIndex,
            riseOnHover: true,
          });

          let popupContent = `
            <b>${index + 1}. ${stop.name}</b><br>
            ${stop.address}<br>
          `;

          if (isSelected) {
            popupContent += `<span style="background-color: #8b4513; color: white; padding: 2px 6px; border-radius: 3px; font-size: 0.85em; font-weight: bold;">✓ SELECTED</span><br>`;
            
            if (stop.fuel_capacity_at_arrival !== undefined) {
              popupContent += `<b>Fuel Capacity at Arrival:</b> ${stop.fuel_capacity_at_arrival.toFixed(2)} gal<br>`;
            }
            if (stop.fuel_purchased_gallons !== undefined && stop.fuel_purchased_gallons > 0) {
              popupContent += `<b>Fuel Purchased:</b> ${stop.fuel_purchased_gallons.toFixed(2)} gal<br>`;
            }
            if (stop.fuel_cost_at_stop !== undefined && stop.fuel_cost_at_stop > 0) {
              popupContent += `<b>Fuel Cost at Stop:</b> $${stop.fuel_cost_at_stop.toFixed(2)}<br>`;
            }
          }

          if (stop.price_per_gallon !== undefined) {
            popupContent += `<b>Price:</b> $${stop.price_per_gallon.toFixed(3)}/gal<br>`;
          }
          if (stop.distance_along_route_miles !== undefined) {
            popupContent += `<b>Distance:</b> ${stop.distance_along_route_miles.toFixed(1)} miles`;
          }

          fuelMarker.bindPopup(popupContent);
          fuelMarker.addTo(map);
          markersRef.current.push(fuelMarker);
        }
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
          <h1>🗺️ Route Map</h1>
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

  const selectedStopsCount = routeData.fuel_stops
    ? routeData.fuel_stops.filter(stop => stop.is_selected === true).length
    : 0;

  return (
    <div className="container">
      <div className="header">
        <h1>🗺️ Route Map</h1>
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
          {routeData.total_fuel_cost && routeData.total_fuel_cost > 0 && (
            <div className="summary-item">
              <label>Total Fuel Cost</label>
              <div className="value" style={{ color: '#059669' }}>
                ${routeData.total_fuel_cost.toFixed(2)}
              </div>
            </div>
          )}
          <div className="summary-item">
            <label>Selected Stops</label>
            <div className="value" style={{ color: '#8b4513', fontWeight: 700 }}>
              {selectedStopsCount}
            </div>
          </div>
          {routeData.total_fuel_gallons && routeData.total_fuel_gallons > 0 && (
            <div className="summary-item">
              <label>Fuel Needed</label>
              <div className="value">
                {routeData.total_fuel_gallons.toFixed(1)} gal
              </div>
            </div>
          )}
          {routeData.algorithm && (
            <div className="summary-item">
              <label>Algorithm</label>
              <div className="value" style={{ textTransform: 'capitalize' }}>
                {routeData.algorithm}
              </div>
            </div>
          )}
          {routeData.initial_fuel_gallons !== null && routeData.initial_fuel_gallons !== undefined && (
            <div className="summary-item">
              <label>Initial Fuel</label>
              <div className="value">
                {routeData.initial_fuel_gallons.toFixed(1)} gal
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
            <div className="legend-icon" style={{ backgroundColor: '#8b4513', width: '22px', height: '22px' }}></div>
            <span><strong>Selected Fuel Stop</strong></span>
          </div>
          {routeData.fuel_stops && routeData.fuel_stops.some(stop => !stop.is_selected) && (
            <div className="legend-item">
              <div className="legend-icon" style={{ backgroundColor: '#3b82f6', width: '18px', height: '18px' }}></div>
              <span>Other Fuel Stop</span>
            </div>
          )}
        </div>
        {routeData.fuel_stops && routeData.fuel_stops.some(stop => !stop.is_selected) && (
          <div className="legend-toggle">
            <label>
              <input
                type="checkbox"
                checked={showAllStops}
                onChange={(e) => setShowAllStops(e.target.checked)}
              />
              <span>Show All Fuel Stops</span>
            </label>
          </div>
        )}
      </div>

      <div className="map-container">
        <div ref={mapRef} id="map"></div>
      </div>
    </div>
  );
}

export default RouteMap;

