import { NavLink } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import {
  LayoutDashboard, Package, ShoppingCart, Users, Settings, Truck, Database,
  LogOut, Box
} from 'lucide-react';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/products', icon: Package, label: 'Products' },
  { to: '/orders', icon: ShoppingCart, label: 'Orders' },
  { to: '/suppliers', icon: Truck, label: 'Suppliers' },
  { to: '/users', icon: Users, label: 'Users' },
  { to: '/sap-sync', icon: Database, label: 'SAP Sync' },
  { to: '/settings', icon: Settings, label: 'Account Settings' },
];

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo-box">
          <Box size={22} color="#ffffff" />
        </div>
        <div className="sidebar-brand">
          <span className="sidebar-title">Inventory MS</span>
          <span className="sidebar-subtitle">VST Tillers & Tractors</span>
        </div>
      </div>

      <nav className="sidebar-nav">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
          >
            <Icon size={19} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <a href="#logout" className="logout-btn" onClick={(e) => { e.preventDefault(); alert('Logged out (simulated)'); }}>
          <LogOut size={18} />
          <span>Logout</span>
        </a>
      </div>
    </aside>
  );
}
