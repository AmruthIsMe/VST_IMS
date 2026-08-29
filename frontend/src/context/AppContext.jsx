import { useState, createContext, useContext } from 'react';

const AppContext = createContext();

export function AppProvider({ children }) {
  const [theme, setTheme] = useState('light');
  const [notifications, setNotifications] = useState(true);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const toggleTheme = () => setTheme(t => t === 'light' ? 'dark' : 'light');
  const toggleSidebar = () => setSidebarCollapsed(c => !c);
  const toggleMobileMenu = () => setMobileMenuOpen(m => !m);
  const closeMobileMenu = () => setMobileMenuOpen(false);

  return (
    <AppContext.Provider value={{
      theme, toggleTheme,
      notifications, setNotifications,
      sidebarCollapsed, toggleSidebar,
      mobileMenuOpen, toggleMobileMenu, closeMobileMenu,
    }}>
      <div className={theme === 'dark' ? 'dark-theme' : ''}>
        {children}
      </div>
    </AppContext.Provider>
  );
}

export const useApp = () => useContext(AppContext);
