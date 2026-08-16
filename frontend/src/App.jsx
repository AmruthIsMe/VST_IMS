import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AppProvider } from './context/AppContext';
import Sidebar from './components/Sidebar';
import Dashboard from './pages/Dashboard';
import Products from './pages/Products';
import Orders from './pages/Orders';
import Suppliers from './pages/Suppliers';
import Users from './pages/Users';
import Settings from './pages/Settings';
import SapSync from './pages/SapSync';
import Forecasting from './pages/Forecasting';
import Genie from './pages/Genie';
import './App.css';

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppProvider>
        <BrowserRouter>
          <div className="app-layout">
            <Sidebar />
            <main className="main-content">
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/products" element={<Products />} />
                <Route path="/orders" element={<Orders />} />
                <Route path="/suppliers" element={<Suppliers />} />
                <Route path="/forecasting" element={<Forecasting />} />
                <Route path="/genie" element={<Genie />} />
                <Route path="/users" element={<Users />} />
                <Route path="/sap-sync" element={<SapSync />} />
                <Route path="/settings" element={<Settings />} />
              </Routes>
            </main>
          </div>
        </BrowserRouter>
      </AppProvider>
    </QueryClientProvider>
  );
}
