import { useState } from 'react';
import Header from '../components/Header';
import { Settings as SettingsIcon } from 'lucide-react';
import { useApp } from '../context/AppContext';

export default function Settings({ onMenuToggle }) {
  const { theme, toggleTheme, notifications, setNotifications } = useApp();
  const [name, setName] = useState('Admin User');
  const [email, setEmail] = useState('admin@vst.com');
  const [saved, setSaved] = useState(false);

  const handleSave = (e) => {
    e.preventDefault();
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div>
      <Header onMenuToggle={onMenuToggle} />

      <div className="page-container">
        <div className="page-banner">
          <div className="page-banner-icon">
            <SettingsIcon size={24} />
          </div>
          <h1 className="page-banner-title">Account Settings</h1>
        </div>

        <div className="chart-card" style={{ marginBottom: 20 }}>
          <h3 style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>Personal Information</h3>
          <form onSubmit={handleSave}>
            <div className="form-group"><label>Name</label><input value={name} onChange={(e) => setName(e.target.value)} /></div>
            <div className="form-group"><label>Email</label><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
            <button type="submit" className="btn-primary" style={{ marginTop: 12 }}>{saved ? 'Saved!' : 'Save Changes'}</button>
          </form>
        </div>

        <div className="chart-card">
          <h3 style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>Preferences</h3>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 0', borderBottom: '1px solid #eaecf0' }}>
            <div>
              <strong>Dark Mode</strong>
              <div style={{ fontSize: 12, color: '#667085' }}>Switch interface theme</div>
            </div>
            <input type="checkbox" checked={theme === 'dark'} onChange={toggleTheme} style={{ width: 20, height: 20 }} />
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 0' }}>
            <div>
              <strong>Email Notifications</strong>
              <div style={{ fontSize: 12, color: '#667085' }}>Receive alerts for low stock levels</div>
            </div>
            <input type="checkbox" checked={notifications} onChange={() => setNotifications(!notifications)} style={{ width: 20, height: 20 }} />
          </div>
        </div>
      </div>
    </div>
  );
}
