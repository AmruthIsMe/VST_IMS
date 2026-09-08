import { useState, createContext, useContext, useEffect, useCallback } from 'react';
import api from '../services/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(() => localStorage.getItem('vst_token'));
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // ── AUTH TOGGLE: Set to true to re-enable token validation ──
    const AUTH_ENABLED = false;
    // ── END AUTH TOGGLE ──

    if (!AUTH_ENABLED) {
      setUser({
        id: "00000000-0000-0000-0000-000000000000",
        user_id: "USR-04",
        name: "Dev User",
        email: "dev@vst.com",
        role: "Admin",
        status: "Active",
      });
      setToken("dev-bypass-token");
      setLoading(false);
      return;
    }

    if (token) {
      api.defaults.headers.common['Authorization'] = `Bearer ${token}`;
      api.get('/auth/me')
        .then(r => setUser(r.data))
        .catch(() => { logout(); })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const login = useCallback(async (username, password) => {
    const res = await api.post('/auth/login', { username, password });
    const { access_token, user: userData } = res.data;
    localStorage.setItem('vst_token', access_token);
    api.defaults.headers.common['Authorization'] = `Bearer ${access_token}`;
    setToken(access_token);
    setUser(userData);
    return userData;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('vst_token');
    delete api.defaults.headers.common['Authorization'];
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, login, logout, loading, isAuthenticated: !!token && !!user }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
