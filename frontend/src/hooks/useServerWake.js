import { useState, useEffect, useRef } from 'react';

const HEALTH_URL = `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'}/health`;
const SLOW_THRESHOLD_MS = 2500; // show wake screen after this delay
const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 4000;

/**
 * Fires GET /api/health on mount and detects if the server is cold-starting.
 *
 * Returns:
 *   isWaking   — true while the server is taking longer than SLOW_THRESHOLD_MS
 *   serverReady — true once the health check resolves successfully
 */
export function useServerWake() {
  const [isWaking, setIsWaking] = useState(false);
  const [serverReady, setServerReady] = useState(false);
  const attemptRef = useRef(0);
  const slowTimerRef = useRef(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;

    async function pingHealth() {
      // Start the "slow server" timer — if health check hasn't resolved in
      // SLOW_THRESHOLD_MS, show the wake screen.
      slowTimerRef.current = setTimeout(() => {
        if (mountedRef.current) setIsWaking(true);
      }, SLOW_THRESHOLD_MS);

      let success = false;

      while (attemptRef.current < MAX_RETRIES && !success) {
        try {
          const res = await fetch(HEALTH_URL, {
            method: 'GET',
            // Long timeout — Render cold-starts can take up to 60s
            signal: AbortSignal.timeout(65000),
          });

          if (res.ok) {
            success = true;
          }
        } catch {
          // Network error / timeout — wait before retrying
          attemptRef.current += 1;
          if (attemptRef.current < MAX_RETRIES) {
            await new Promise((r) => setTimeout(r, RETRY_DELAY_MS));
          }
        }

        if (success) break;
        attemptRef.current += 1;
      }

      // Clear slow-timer in case health resolved within the threshold
      clearTimeout(slowTimerRef.current);

      if (mountedRef.current) {
        setServerReady(true);
        // Small delay so the fade-out CSS transition looks smooth
        setTimeout(() => {
          if (mountedRef.current) setIsWaking(false);
        }, 600);
      }
    }

    pingHealth();

    return () => {
      mountedRef.current = false;
      clearTimeout(slowTimerRef.current);
    };
  }, []);

  return { isWaking, serverReady };
}
