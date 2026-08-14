import { useState, useEffect } from 'react';

export default function Header({ pageSubtitle, locationText }) {
  const [timeStr, setTimeStr] = useState('');

  useEffect(() => {
    const update = () => {
      const now = new Date();
      setTimeStr(now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true }));
    };
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <header className="top-header">
      <div className="header-left">
        <h1 className="header-title">VST Tillers & Tractors</h1>
        <p className="header-subtitle">Supply Chain Intelligence Platform</p>
      </div>

      {locationText && (
        <div className="header-center">
          <div className="center-title">Real-time Spares & Pumps Inventory</div>
          <div className="center-location">{locationText}</div>
        </div>
      )}

      <div className="header-right">
        <span className="live-badge">
          <span className="live-dot"></span> LIVE
        </span>
        <span className="header-time">13 Aug 2026, {timeStr || '12:08 pm'}</span>
      </div>
    </header>
  );
}
