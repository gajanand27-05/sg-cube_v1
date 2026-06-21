import React from 'react'
import type { AssistantStatus, SystemStats, WsEvent } from '../hooks/useWebSocket'

interface Props {
  status: AssistantStatus
  systemStats: SystemStats
  events?: WsEvent[]
}

export function StatusPanel({ status, systemStats, events = [] }: Props) {
  const { 
    cpu_percent = 0, 
    memory_percent = 0, 
    memory_used_gb = 0, 
    memory_total_gb = 0,
    disk_percent = 0,
    disk_used_gb = 0,
    disk_total_gb = 0,
    net_down_bps = 0,
    net_up_bps = 0
  } = systemStats || {};

  const formatNet = (bps: number) => {
    if (bps < 1024) return `${bps.toFixed(0)} B/s`;
    if (bps < 1024 * 1024) return `${(bps / 1024).toFixed(1)} KB/s`;
    return `${(bps / (1024 * 1024)).toFixed(2)} MB/s`;
  };

  const recentEvents = events.slice(-8).reverse();

  return (
    <aside className="status-panel-right">
      <div className="sp-section">
        <h3 className="sp-header">ASSISTANT STATUS</h3>
        <div className="agent-status-block">
          <div className="sp-monitor-item">
            <div className="sp-label">STATE</div>
            <div className={`status-value ${status.state?.toLowerCase()}`}>{status.state || 'IDLE'}</div>
          </div>
          <div className="sp-monitor-item">
            <div className="sp-label">AGENT</div>
            <div className="status-value">{status.currentAgent || '—'}</div>
          </div>
          <div className="sp-monitor-item">
            <div className="sp-label">CONFIDENCE</div>
            <div className="status-value">{status.confidence?.toFixed(0) || '—'}%</div>
          </div>
          <div className="sp-monitor-item">
            <div className="sp-label">MEMORY HITS</div>
            <div className="status-value">{events.filter(e => e.type === 'state_changed').length}</div>
          </div>
        </div>
      </div>

      <div className="sp-section">
        <h3 className="sp-header">SYSTEM MONITOR</h3>
        
        <div className="sp-monitor-item">
          <div className="sp-label">CPU USAGE</div>
          <div className="sp-chart-row">
            <div className="radial-chart">
              <svg viewBox="0 0 36 36">
                <path className="circle-bg" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                <path className="circle" strokeDasharray={`${cpu_percent}, 100`} d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                <text x="18" y="21" className="percentage">{cpu_percent}%</text>
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
                <path className="circle" strokeDasharray={`${memory_percent}, 100`} d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                <text x="18" y="21" className="percentage">{memory_percent}%</text>
              </svg>
            </div>
            <div className="sp-bars-container">
               <div className="sp-stats">{memory_used_gb} GiB / {memory_total_gb} GiB</div>
               <div className="sp-bar-track">
                  {Array.from({length: 12}).map((_, i) => (
                    <div key={i} className={`sp-bar-segment ${i < (memory_percent / 100) * 12 ? 'active' : ''}`}></div>
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
                <path className="circle" strokeDasharray={`${disk_percent}, 100`} d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                <text x="18" y="21" className="percentage">{disk_percent}%</text>
              </svg>
            </div>
            <div className="sp-bars-container">
               <div className="sp-stats">{disk_used_gb} GiB / {disk_total_gb} GiB</div>
               <div className="sp-bar-track">
                  {Array.from({length: 12}).map((_, i) => (
                    <div key={i} className={`sp-bar-segment ${i < (disk_percent / 100) * 12 ? 'active' : ''}`}></div>
                  ))}
               </div>
            </div>
          </div>
        </div>

        <div className="sp-monitor-item network">
          <div className="sp-label">NETWORK <span className="net-stats"><span className="arr-down">↓</span> {formatNet(net_down_bps)}   <span className="arr-up">↑</span> {formatNet(net_up_bps)}</span></div>
          <div className="sp-wave-container">
               <svg width="100%" height="24" preserveAspectRatio="none">
                  <path d="M0,12 Q5,24 10,12 T20,12 T30,12 T40,12 T50,12 T60,12 T70,12 T80,12 T90,12 T100,12 T110,12 T120,12 T130,12" fill="none" stroke="var(--border-bright)" strokeWidth="1.5" />
                  <path d="M0,12 Q5,0 10,12 T20,12 T30,12 T40,12 T50,12 T60,12 T70,12 T80,12 T90,12 T100,12 T110,12 T120,12 T130,12" fill="none" stroke="var(--border-bright)" strokeWidth="1.5" opacity="0.3" />
               </svg>
          </div>
        </div>
      </div>

      <div className="sp-section no-border">
        <h3 className="sp-header">LIVE EVENTS</h3>
        <div className="activity-log">
          {recentEvents.length === 0 && (
            <div className="log-line"><span className="text-dim">Waiting for events...</span></div>
          )}
          {recentEvents.map((e, i) => (
            <div key={i} className="log-line">
              <span className="event-type">{e.type.replace('Event', '')}</span>
              <span className="event-detail">
                {e.payload?.text as string || e.payload?.action as string || e.payload?.agent_name as string || ''}
              </span>
            </div>
          ))}
        </div>
      </div>
    </aside>
  )
}
