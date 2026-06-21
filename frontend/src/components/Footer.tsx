import { useState, useEffect } from 'react'
import type { SystemStats } from '../hooks/useWebSocket'

interface Props {
  systemStats?: SystemStats
}

export function Footer({ systemStats }: Props) {
  const { temp_c, cpu_percent = 0 } = systemStats || {};
  const [time, setTime] = useState(new Date().toLocaleTimeString());

  useEffect(() => {
    const interval = setInterval(() => setTime(new Date().toLocaleTimeString()), 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <footer className="app-footer">
      <div className="footer-left">
        <div className="reactor-icon">
          <div className="reactor-core"></div>
        </div>
        <div className="footer-build">
          <div className="footer-title">SG CUBE v2.0</div>
          <div className="footer-subtitle">AGENTIC BUILD</div>
        </div>
      </div>
      
      <div className="footer-center">
        <div className="system-load">
          <div className="load-label">CPU LOAD</div>
          <div className="load-bars">
            {Array.from({ length: 20 }).map((_, i) => {
               const maxBars = 20;
               const activeThreshold = (cpu_percent / 100) * maxBars;
               const jitter = (Math.random() - 0.5) * 4; 
               const isActive = i < (activeThreshold + jitter);
               const isWarn = i > 14 && isActive;
               return <div key={i} className={`load-bar ${isActive ? (isWarn ? 'warning' : 'active') : ''}`} style={{ height: `${20 + Math.random() * 80}%` }}></div>
            })}
          </div>
        </div>
        <div className="temp-module">
          <div className="reactor-icon small">
             <div className="reactor-core"></div>
          </div>
          <div className="temp-info">
            <div className="temp-label">TEMP</div>
            <div className="temp-value">{temp_c !== null ? `${temp_c}°C` : 'N/A'}</div>
          </div>
        </div>
      </div>

      <div className="footer-right">
        <div className="clock-icon">
          <svg viewBox="0 0 24 24" width="24" height="24">
            <circle cx="12" cy="12" r="10" fill="none" stroke="var(--text-dim)" strokeWidth="2" />
            <path d="M12 6v6l4 2" fill="none" stroke="var(--border-bright)" strokeWidth="2" />
          </svg>
        </div>
        <div className="time-info">
          <div className="time-label">TIME</div>
          <div className="time-value">{time}</div>
        </div>
      </div>
    </footer>
  );
}
