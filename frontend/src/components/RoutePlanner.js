import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import './RoutePlanner.css';

/* global APP_API_URL */
const API_BASE_URL =
  (typeof APP_API_URL !== 'undefined' && APP_API_URL) ||
  process.env.REACT_APP_API_URL ||
  'http://localhost:8000';

function RoutePlanner() {
  const [startLocation, setStartLocation] = useState('');
  const [endLocation, setEndLocation] = useState('');
  const [algorithm, setAlgorithm] = useState('greedy');
  const [initialFuelGallons, setInitialFuelGallons] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingShowRoute, setLoadingShowRoute] = useState(false);
  const [error, setError] = useState('');
  const [startSuggestions, setStartSuggestions] = useState([]);
  const [endSuggestions, setEndSuggestions] = useState([]);
  const [showStartSuggestions, setShowStartSuggestions] = useState(false);
  const [showEndSuggestions, setShowEndSuggestions] = useState(false);
  const startInputRef = useRef(null);
  const endInputRef = useRef(null);
  const startSuggestionsRef = useRef(null);
  const endSuggestionsRef = useRef(null);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      const response = await fetch(`${API_BASE_URL}/api/route/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          start_location: startLocation,
          end_location: endLocation,
          algorithm: algorithm,
          initial_fuel_gallons: initialFuelGallons ? parseFloat(initialFuelGallons) : null,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to plan route');
      }

      // Navigate to map view with route data
      navigate('/map', { state: { routeData: data } });
    } catch (err) {
      setError(`Error: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleShowRouteAndStations = async () => {
    if (!startLocation || !endLocation) {
      setError('Please enter both start and end locations');
      return;
    }

    setLoadingShowRoute(true);
    setError('');

    try {
      const response = await fetch(`${API_BASE_URL}/api/route/optimize/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          start_location: startLocation,
          end_location: endLocation,
          max_distance_km: 5.0,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Failed to show route and nearby stations');
      }

      // Navigate to stations map view with route data
      navigate('/stations-map', { state: { routeData: data } });
    } catch (err) {
      setError(`Error: ${err.message}`);
    } finally {
      setLoadingShowRoute(false);
    }
  };

  // Debounce function
  const debounce = (func, wait) => {
    let timeout;
    return function executedFunction(...args) {
      const later = () => {
        clearTimeout(timeout);
        func(...args);
      };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  };

  // Fetch autocomplete suggestions
  const fetchSuggestions = async (query, setSuggestions, setShowSuggestions) => {
    if (!query || query.length < 2) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }

    try {
      const response = await fetch(`${API_BASE_URL}/api/route/autocomplete/?q=${encodeURIComponent(query)}`);
      const data = await response.json();
      
      if (Array.isArray(data)) {
        setSuggestions(data);
        setShowSuggestions(data.length > 0);
      } else {
        setSuggestions([]);
        setShowSuggestions(false);
      }
    } catch (err) {
      console.error('Error fetching suggestions:', err);
      setSuggestions([]);
      setShowSuggestions(false);
    }
  };

  // Debounced versions of fetchSuggestions
  const debouncedFetchStartSuggestions = useRef(
    debounce((query) => fetchSuggestions(query, setStartSuggestions, setShowStartSuggestions), 300)
  ).current;

  const debouncedFetchEndSuggestions = useRef(
    debounce((query) => fetchSuggestions(query, setEndSuggestions, setShowEndSuggestions), 300)
  ).current;

  // Handle start location input change
  const handleStartLocationChange = (e) => {
    const value = e.target.value;
    setStartLocation(value);
    debouncedFetchStartSuggestions(value);
  };

  // Handle end location input change
  const handleEndLocationChange = (e) => {
    const value = e.target.value;
    setEndLocation(value);
    debouncedFetchEndSuggestions(value);
  };

  // Handle suggestion selection
  const handleStartSuggestionClick = (suggestion) => {
    setStartLocation(suggestion.display_name);
    setStartSuggestions([]);
    setShowStartSuggestions(false);
  };

  const handleEndSuggestionClick = (suggestion) => {
    setEndLocation(suggestion.display_name);
    setEndSuggestions([]);
    setShowEndSuggestions(false);
  };

  // Close suggestions when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (
        startInputRef.current &&
        !startInputRef.current.contains(event.target) &&
        startSuggestionsRef.current &&
        !startSuggestionsRef.current.contains(event.target)
      ) {
        setShowStartSuggestions(false);
      }
      if (
        endInputRef.current &&
        !endInputRef.current.contains(event.target) &&
        endSuggestionsRef.current &&
        !endSuggestionsRef.current.contains(event.target)
      ) {
        setShowEndSuggestions(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  return (
    <div className="container">
      <div className="header">
        <h1>🚛 Fuel Route Optimizer</h1>
        <p>Find the optimal fuel stops for your journey</p>
      </div>

      <div className="content">
        <form onSubmit={handleSubmit}>
          <div className="form-group autocomplete-wrapper">
            <label htmlFor="startLocation">Start Location</label>
            <div className="autocomplete-container" ref={startInputRef}>
              <input
                type="text"
                id="startLocation"
                name="start_location"
                placeholder="e.g., New York, NY"
                value={startLocation}
                onChange={handleStartLocationChange}
                onFocus={() => startSuggestions.length > 0 && setShowStartSuggestions(true)}
                required
              />
              {showStartSuggestions && startSuggestions.length > 0 && (
                <ul className="autocomplete-suggestions" ref={startSuggestionsRef}>
                  {startSuggestions.map((suggestion, index) => (
                    <li
                      key={index}
                      onClick={() => handleStartSuggestionClick(suggestion)}
                      className="autocomplete-suggestion"
                    >
                      {suggestion.display_name}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div className="form-group autocomplete-wrapper">
            <label htmlFor="endLocation">End Location</label>
            <div className="autocomplete-container" ref={endInputRef}>
              <input
                type="text"
                id="endLocation"
                name="end_location"
                placeholder="e.g., Los Angeles, CA"
                value={endLocation}
                onChange={handleEndLocationChange}
                onFocus={() => endSuggestions.length > 0 && setShowEndSuggestions(true)}
                required
              />
              {showEndSuggestions && endSuggestions.length > 0 && (
                <ul className="autocomplete-suggestions" ref={endSuggestionsRef}>
                  {endSuggestions.map((suggestion, index) => (
                    <li
                      key={index}
                      onClick={() => handleEndSuggestionClick(suggestion)}
                      className="autocomplete-suggestion"
                    >
                      {suggestion.display_name}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="algorithm">Algorithm</label>
            <select
              id="algorithm"
              name="algorithm"
              value={algorithm}
              onChange={(e) => setAlgorithm(e.target.value)}
            >
              <option value="greedy">Greedy</option>
              <option value="dijkstra">Dijkstra</option>
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="initialFuelGallons">Initial Fuel (Gallons)</label>
            <input
              type="number"
              id="initialFuelGallons"
              name="initial_fuel_gallons"
              placeholder="e.g., 10 (optional)"
              value={initialFuelGallons}
              onChange={(e) => setInitialFuelGallons(e.target.value)}
              min="0"
              max="50"
              step="0.1"
            />
          </div>

          <button type="submit" disabled={loading || loadingShowRoute}>
            {loading ? 'Planning Route...' : 'Plan Route'}
          </button>
        </form>

        <button 
          type="button" 
          onClick={handleShowRouteAndStations} 
          disabled={loading || loadingShowRoute}
          style={{ marginTop: '10px' }}
        >
          {loadingShowRoute ? 'Loading Route...' : 'Show Route and Nearby Fuel Stops'}
        </button>

        {(loading || loadingShowRoute) && (
          <div className="loading">
            <div className="spinner"></div>
            <p>{loading ? 'Calculating optimal route and fuel stops...' : 'Loading route and nearby stations...'}</p>
          </div>
        )}

        {error && <div className="error">{error}</div>}
      </div>
    </div>
  );
}

export default RoutePlanner;

