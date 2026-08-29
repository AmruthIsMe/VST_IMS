import { NavLink } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import { useAuth } from '../context/AuthContext';
import {
  LayoutDashboard, Package, ShoppingCart, Users, Settings, Truck, Database,
  LogOut, Box, TrendingUp, Sparkles, X
} from 'lucide-react';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/products', icon: Package, label: 'Products' },
  { to: '/orders', icon: ShoppingCart, label: 'Orders' },
  { to: '/suppliers', icon: Truck, label: 'Suppliers' },
  { to: '/forecasting', icon: TrendingUp, label: 'Demand Forecast' },
  { to: '/genie', icon: Sparkles, label: 'Genie' },
  { to: '/users', icon: Users, label: 'Users' },
  { to: '/sap-sync', icon: Database, label: 'SAP Sync' },
  { to: '/settings', icon: Settings, label: 'Account Settings' },
];

const ROLE_COLORS = {
  Manager: { bg: '#ecfdf3', text: '#027a48' },
  Admin: { bg: '#eff8ff', text: '#175cd3' },
  Cashier: { bg: '#fffaeb', text: '#b54708' },
};

export default function Sidebar({ isMobileOpen, onMobileClose }) {
  const { logout } = useAuth();
  const { user } = useAuth();
  const roleColor = ROLE_COLORS[user?.role] || ROLE_COLORS.Manager;

  return (
    <>
      {isMobileOpen && <div className="sidebar-overlay" onClick={onMobileClose} />}
      <aside className={`sidebar ${isMobileOpen ? 'sidebar-mobile-open' : ''}`}>
        <div className="sidebar-header">
          <div className="sidebar-logo-box">
            <img src="/VST(logo).png" alt="VST Logo" className="sidebar-logo-img" />
          </div>
          <div className="sidebar-brand">
            <span className="sidebar-title">Inventory MS</span>
            <span className="sidebar-subtitle">VST Tillers & Tractors</span>
          </div>
          <button className="sidebar-close-btn" onClick={onMobileClose}>
            <X size={20} />
          </button>
        </div>

        <nav className="sidebar-nav">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
              onClick={onMobileClose}
            >
              <Icon size={19} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          {user && (
            <div className="sidebar-user-info">
              <div className="sidebar-user-avatar">
                {user.name?.charAt(0) || 'U'}
              </div>
              <div className="sidebar-user-details">
                <span className="sidebar-user-name">{user.name}</span>
                <span
                  className="sidebar-user-role"
                  style={{ backgroundColor: roleColor.bg, color: roleColor.text }}
                >
                  {user.role}
                </span>
              </div>
            </div>
          )}
          <a href="#logout" className="logout-btn" onClick={(e) => { e.preventDefault(); logout(); }}>
            <LogOut size={18} />
            <span>Logout</span>
          </a>
        </div>
      </aside>
    </>
  );
}
