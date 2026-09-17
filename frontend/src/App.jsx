import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AppProvider, useApp } from './context/AppContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import ProtectedRoute from './components/ProtectedRoute';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Products from './pages/Products';
import Orders from './pages/Orders';
import Suppliers from './pages/Suppliers';
import Users from './pages/Users';
import Settings from './pages/Settings';
import SapSync from './pages/SapSync';
import Forecasting from './pages/Forecasting';
import Genie from './pages/Genie';
import ServerWakeScreen from './components/ServerWakeScreen';
import { useServerWake } from './hooks/useServerWake';
import './App.css';

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } },
});

function AppContent() {
  const { isAuthenticated } = useAuth();
  const { mobileMenuOpen, closeMobileMenu, toggleMobileMenu } = useApp();

  // ── AUTH TOGGLE: Set to false to re-enable login gate ──
  const AUTH_BYPASS = true;
  // ── END AUTH TOGGLE ──

  if (!isAuthenticated && !AUTH_BYPASS) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <div className="app-layout">
      <Sidebar isMobileOpen={mobileMenuOpen} onMobileClose={closeMobileMenu} />
      <main className="main-content">
        <Routes>
          <Route path="/" element={<Dashboard onMenuToggle={toggleMobileMenu} />} />
          <Route path="/products" element={<Products onMenuToggle={toggleMobileMenu} />} />
          <Route path="/orders" element={<Orders onMenuToggle={toggleMobileMenu} />} />
          <Route path="/suppliers" element={<Suppliers onMenuToggle={toggleMobileMenu} />} />
          <Route path="/forecasting" element={<Forecasting onMenuToggle={toggleMobileMenu} />} />
          <Route path="/genie" element={<Genie onMenuToggle={toggleMobileMenu} />} />
          <Route path="/users" element={<Users onMenuToggle={toggleMobileMenu} />} />
          <Route path="/sap-sync" element={<SapSync onMenuToggle={toggleMobileMenu} />} />
          <Route path="/settings" element={<Settings onMenuToggle={toggleMobileMenu} />} />
          <Route path="/login" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  const { isWaking, serverReady } = useServerWake();

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <AppProvider>
          <BrowserRouter>
            {/* Show animated wake screen on top during cold-starts.
                The app mounts in the background so all providers and
                React Query are ready the moment the server responds. */}
            {isWaking && <ServerWakeScreen ready={serverReady} />}
            <AppContent />
          </BrowserRouter>
        </AppProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
