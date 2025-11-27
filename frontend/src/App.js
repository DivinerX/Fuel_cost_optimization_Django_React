import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import RoutePlanner from './components/RoutePlanner';
import RouteMap from './components/RouteMap';
import RouteStationsMap from './components/RouteStationsMap';
import './App.css';

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<RoutePlanner />} />
        <Route path="/map" element={<RouteMap />} />
        <Route path="/stations-map" element={<RouteStationsMap />} />
      </Routes>
    </Router>
  );
}

export default App;

