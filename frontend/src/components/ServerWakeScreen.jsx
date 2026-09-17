import { useEffect, useState } from 'react';
import './ServerWakeScreen.css';

const MESSAGES = [
  'Connecting to cloud server\u2026',
  'Server is waking up from idle\u2026',
  'Almost there, hang tight\u2026',
  'Initialising database connection\u2026',
];

/**
 * Full-page animated overlay shown when the backend is cold-starting.
 * Fades out automatically once `ready` becomes true.
 */
export default function ServerWakeScreen({ ready }) {
  const [msgIndex, setMsgIndex] = useState(0);
  const [progress, setProgress] = useState(0);
  const [visible, setVisible] = useState(true);

  // Cycle through reassuring status messages every 5 seconds
  useEffect(() => {
    const id = setInterval(() => {
      setMsgIndex((i) => (i + 1) % MESSAGES.length);
    }, 5000);
    return () => clearInterval(id);
  }, []);

  // Animate the progress bar from 0 → 92% over ~28s (never quite reaches 100
  // until the server actually responds, giving a honest feel)
  useEffect(() => {
    let current = 0;
    const id = setInterval(() => {
      current += 100 / (28000 / 120); // step size to fill in ~28s at 120ms intervals
      setProgress(Math.min(current, 92));
    }, 120);
    return () => clearInterval(id);
  }, []);

  // When the server is ready, jump progress to 100% then fade out
  useEffect(() => {
    if (ready) {
      setProgress(100);
      const id = setTimeout(() => setVisible(false), 700);
      return () => clearTimeout(id);
    }
  }, [ready]);

  if (!visible) return null;

  return (
    <div className={`server-wake-overlay ${ready ? 'server-wake-overlay--exit' : ''}`}>
      <div className="server-wake-card">
        {/* Animated icon */}
        <div className="server-wake-icon-wrapper">
          <div className="server-wake-ring server-wake-ring--outer" />
          <div className="server-wake-ring server-wake-ring--inner" />
          <div className="server-wake-icon">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
              <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
              <line x1="6" y1="6" x2="6.01" y2="6" />
              <line x1="6" y1="18" x2="6.01" y2="18" />
            </svg>
          </div>
        </div>

        {/* Heading */}
        <h2 className="server-wake-title">Server Waking Up</h2>
        <p className="server-wake-subtitle">
          ⚡ We use a free-tier cloud server that sleeps after inactivity.
          <br />
          <strong>This usually takes roughly 20 seconds.</strong>
        </p>

        {/* Progress bar */}
        <div className="server-wake-progress-track">
          <div
            className="server-wake-progress-fill"
            style={{ width: `${progress}%` }}
          />
        </div>
        <div className="server-wake-progress-label">
          {ready ? '✓ Connected!' : `${Math.round(progress)}%`}
        </div>

        {/* Cycling status message */}
        <p className="server-wake-status" key={msgIndex}>
          {MESSAGES[msgIndex]}
        </p>

        {/* Animated dots */}
        <div className="server-wake-dots">
          <span className="server-wake-dot" style={{ animationDelay: '0ms' }} />
          <span className="server-wake-dot" style={{ animationDelay: '200ms' }} />
          <span className="server-wake-dot" style={{ animationDelay: '400ms' }} />
        </div>
      </div>
    </div>
  );
}
