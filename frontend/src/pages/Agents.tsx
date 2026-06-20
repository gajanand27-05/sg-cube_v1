import type { AssistantStatus } from '../hooks/useWebSocket'

interface Props {
  status: AssistantStatus
}

const agents = ['Commander', 'Planner', 'Guardian', 'Operator', 'Watcher']

export function Agents({ status }: Props) {
  return (
    <div className="page">
      <div className="page-header">
        <h1>Agents</h1>
        <span className="page-subtitle">Multi-Agent System</span>
      </div>
      <div className="agents-grid">
        {agents.map((agent) => {
          const active = status.currentAgent?.toLowerCase() === agent.toLowerCase()
          return (
            <div key={agent} className={`agent-card${active ? ' agent-active' : ''}`}>
              <div className="agent-name">{agent}</div>
              <div className="agent-status">
                <span className={`dot ${active ? 'dot-active' : 'dot-idle'}`} />
                {active ? 'Active' : 'Standby'}
              </div>
              {active && <div className="agent-badge">CURRENT</div>}
            </div>
          )
        })}
      </div>
    </div>
  )
}
