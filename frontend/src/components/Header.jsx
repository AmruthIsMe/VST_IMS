import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { Menu, User } from 'lucide-react';

export default function Header({ pageSubtitle, locationText, onMenuToggle }) {
  const [timeStr, setTimeStr] = useState('');
  const { user } = useAuth();

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
        <button className="header-hamburger" onClick={onMenuToggle}>
          <Menu size={22} />
        </button>
        <div className="header-logo-row">
          <img src="/VST(logo).png" alt="VST Logo" className="header-logo" />
          <div>
            <h1 className="header-title">VST Tillers & Tractors</h1>
            <p className="header-subtitle">Supply Chain Intelligence Platform</p>
          </div>
        </div>
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
        {user && (
          <div className="header-user-pill">
            <User size={14} />
            <span>{user.name}</span>
          </div>
        )}
        <span className="header-time">{new Date().toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}, {timeStr || '12:08 pm'}</span>
      </div>
    </header>
  );
}
