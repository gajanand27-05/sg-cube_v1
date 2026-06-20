import React from 'react';

export function Header() {
  return (
    <header className="app-header">
      <div className="header-left">
        <div className="window-controls-container">
          <div className="window-controls">
            <span className="dot red"></span>
            <span className="dot yellow"></span>
            <span className="dot green"></span>
          </div>
        </div>
        <div className="header-title">
          <span className="title-text">SG_CUBE TERMINAL v2.0</span>
        </div>
      </div>
      <div className="header-right">
        <span className="user-info">USER: <span className="highlight">devuser@sgcube</span></span>
      </div>
    </header>
  );
}
