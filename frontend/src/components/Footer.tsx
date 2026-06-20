import React from 'react';

export function Footer() {
  return (
    <footer className="app-footer">
      <div className="footer-left">
        <div className="reactor-icon">
          <div className="reactor-core"></div>
        </div>
        <div className="footer-build">
          <div className="footer-title">SG CUBE v2.0</div>
          <div className="footer-subtitle">BUILD 2024.05.23</div>
        </div>
      </div>
      
      <div className="footer-center">
        <div className="system-load">
          <div className="load-label">SYSTEM LOAD</div>
          <div className="load-bars">
            {Array.from({ length: 20 }).map((_, i) => (
              <div key={i} className={`load-bar ${i < 8 ? 'active' : i < 14 ? 'warning' : ''}`} style={{ height: `${Math.random() * 100}%` }}></div>
            ))}
          </div>
        </div>
        <div className="temp-module">
          <div className="reactor-icon small">
             <div className="reactor-core"></div>
          </div>
          <div className="temp-info">
            <div className="temp-label">TEMP</div>
            <div className="temp-value">58°C</div>
          </div>
          <svg width="60" height="20" className="temp-wave">
             <path d="M0,10 Q10,20 20,10 T40,10 T60,10" fill="none" stroke="var(--border-bright)" strokeWidth="1" />
          </svg>
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
          <div className="time-value">14:35:36</div>
          <div className="time-tz">UTC +0</div>
        </div>
      </div>
    </footer>
  );
}
