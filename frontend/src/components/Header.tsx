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
          <span className="title-text">SG_CUBE v2.0</span>
          <span className="title-sub">AI Operating System</span>
        </div>
      </div>
      <div className="header-right">
        <div className="header-status-dot" />
        <span className="header-status-text">ONYX ONLINE</span>
      </div>
    </header>
  );
}
