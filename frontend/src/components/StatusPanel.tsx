import React from 'react'
import type { AssistantStatus } from '../hooks/useWebSocket'

interface Props {
  status: AssistantStatus
}

export function StatusPanel({ status }: Props) {
  return (
    <aside className="status-panel-right">
      <div className="sp-section">
        <h3 className="sp-header">SYSTEM MONITOR</h3>
        
        <div className="sp-monitor-item">
          <div className="sp-label">CPU USAGE</div>
          <div className="sp-chart-row">
            <div className="radial-chart">
              <svg viewBox="0 0 36 36">
                <path className="circle-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                <path className="circle" strokeDasharray="42, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                <text x="18" y="21" className="percentage">42%</text>
              </svg>
            </div>
            <div className="sp-wave-container">
               <svg width="100%" height="24" preserveAspectRatio="none">
                  <path d="M0,12 Q5,24 10,12 T20,12 T30,12 T40,12 T50,12 T60,12 T70,12 T80,12 T90,12 T100,12 T110,12 T120,12 T130,12" fill="none" stroke="var(--border-bright)" strokeWidth="1.5" />
                  <path d="M0,12 Q5,0 10,12 T20,12 T30,12 T40,12 T50,12 T60,12 T70,12 T80,12 T90,12 T100,12 T110,12 T120,12 T130,12" fill="none" stroke="var(--border-bright)" strokeWidth="1.5" opacity="0.3" />
               </svg>
            </div>
          </div>
        </div>

        <div className="sp-monitor-item">
          <div className="sp-label">MEMORY</div>
          <div className="sp-chart-row">
            <div className="radial-chart">
              <svg viewBox="0 0 36 36">
                <path className="circle-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                <path className="circle" strokeDasharray="35, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                <text x="18" y="21" className="percentage">35%</text>
              </svg>
            </div>
            <div className="sp-bars-container">
               <div className="sp-stats">11.02 GiB / 31.32 GiB</div>
               <div className="sp-bar-track">
                  {Array.from({length: 12}).map((_, i) => (
                    <div key={i} className={`sp-bar-segment ${i < 4 ? 'active' : ''}`}></div>
                  ))}
               </div>
            </div>
          </div>
        </div>

        <div className="sp-monitor-item">
          <div className="sp-label">DISK <span className="sp-label-right"></span></div>
          <div className="sp-chart-row">
            <div className="radial-chart">
              <svg viewBox="0 0 36 36">
                <path className="circle-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                <path className="circle" strokeDasharray="57, 100" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                <text x="18" y="21" className="percentage">57%</text>
              </svg>
            </div>
            <div className="sp-bars-container">
               <div className="sp-stats">178.6 GiB / 314.6 GiB</div>
               <div className="sp-bar-track">
                  {Array.from({length: 12}).map((_, i) => (
                    <div key={i} className={`sp-bar-segment ${i < 7 ? 'active' : ''}`}></div>
                  ))}
               </div>
            </div>
          </div>
        </div>

        <div className="sp-monitor-item network">
          <div className="sp-label">NETWORK <span className="net-stats"><span className="arr-down">↓</span> 3.42 MB/s   <span className="arr-up">↑</span> 1.21 MB/s</span></div>
          <div className="sp-wave-container">
               <svg width="100%" height="24" preserveAspectRatio="none">
                  <path d="M0,12 Q5,24 10,12 T20,12 T30,12 T40,12 T50,12 T60,12 T70,12 T80,12 T90,12 T100,12 T110,12 T120,12 T130,12" fill="none" stroke="var(--border-bright)" strokeWidth="1.5" />
                  <path d="M0,12 Q5,0 10,12 T20,12 T30,12 T40,12 T50,12 T60,12 T70,12 T80,12 T90,12 T100,12 T110,12 T120,12 T130,12" fill="none" stroke="var(--border-bright)" strokeWidth="1.5" opacity="0.3" />
               </svg>
          </div>
        </div>
      </div>

      <div className="sp-section">
        <h3 className="sp-header">SG CUBE SERVICES</h3>
        <div className="services-list">
          <div className="service-header">
            <span>SERVICE</span><span>STATUS</span>
          </div>
          <div className="service-item"><span>sgcube-api</span><span className="dot-status green">RUNNING</span></div>
          <div className="service-item"><span>sgcube-worker</span><span className="dot-status green">RUNNING</span></div>
          <div className="service-item"><span>sgcube-scheduler</span><span className="dot-status green">RUNNING</span></div>
          <div className="service-item"><span>sgcube-notify</span><span className="dot-status yellow">WARNING</span></div>
          <div className="service-item"><span>sgcube-analytics</span><span className="dot-status green">RUNNING</span></div>
        </div>
      </div>

      <div className="sp-section no-border">
        <h3 className="sp-header">ACTIVITY LOG</h3>
        <div className="activity-log">
          <div className="log-line"><span className="time">[14:35:21]</span> <span className="info">INFO</span> User login: devuser</div>
          <div className="log-line"><span className="time">[14:35:24]</span> <span className="info">INFO</span> System health: OK</div>
          <div className="log-line"><span className="time">[14:35:27]</span> <span className="info">INFO</span> Deployment: v2.0.0</div>
          <div className="log-line"><span className="time">[14:35:31]</span> <span className="warn">WARN</span> High memory usage</div>
          <div className="log-line"><span className="time">[14:35:34]</span> <span className="info">INFO</span> Backup completed</div>
        </div>
      </div>
    </aside>
  )
}
