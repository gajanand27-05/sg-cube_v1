import type { AssistantStatus } from '@/hooks/useWebSocket'
import { Brain } from 'lucide-react'
import { cn } from '@/utils/cn'

interface Props {
  status: AssistantStatus
}

export function AICoreWidget({ status }: Props) {
  const isThinking = status.thinking
  const isPlanning = status.state === 'planning'
  const isExecuting = status.state === 'executing' || status.state === 'calling_tool'
  const isWaiting = status.state === 'waiting'
  const isIdle = !isThinking && !isPlanning && !isExecuting && !isWaiting
  const accent = isExecuting ? '#00ff41' : isThinking ? '#a855f7' : isWaiting ? '#eab308' : '#00f3ff'

  return (
    <div className={cn(
      "glass rounded-2xl flex flex-col p-5 transition-all duration-500",
      isThinking ? "shadow-[0_0_22px_rgba(168,85,247,0.25)] bg-purple-500/5" :
      isPlanning ? "shadow-[0_0_22px_rgba(59,130,246,0.3)] bg-blue-500/5 animate-pulse" :
      isExecuting ? "shadow-[0_0_22px_rgba(0,255,65,0.22)] bg-[#00ff41]/5" :
      isWaiting ? "shadow-[0_0_22px_rgba(234,179,8,0.22)] bg-yellow-500/5" :
      "shadow-[0_0_18px_rgba(0,243,255,0.08)]"
    )}>
      <div className="flex justify-between items-center mb-4 border-b border-sgc-border pb-3">
        <div className="flex items-center gap-2 tp-1">
          <Brain size={16} className={cn("transition-colors duration-300", isThinking ? "text-purple-400" : isExecuting ? "text-[#00ff41]" : isWaiting ? "text-yellow-400" : "text-sgc-primary")} />
          AI CORE
        </div>
        <div className={cn("text-[10px] font-mono tracking-widest uppercase transition-colors duration-300", 
          isExecuting ? "text-[#00ff41]" : isThinking ? "text-purple-400" : isWaiting ? "text-yellow-400" : "text-sgc-primary")}>
          {isExecuting ? 'EXECUTING' : isThinking ? 'THINKING' : isWaiting ? 'WAITING' : isPlanning ? 'PLANNING' : 'IDLE'}
        </div>
      </div>

      <div className="flex gap-4 mb-4 items-center">
        {/* Neural network hero */}
        <div className="w-20 h-20 relative shrink-0 flex items-center justify-center">
          <div className="absolute inset-0 border border-sgc-border-bright rounded-full opacity-15 animate-spin-slow" />
          <svg viewBox="0 0 100 100" className="w-full h-full relative" style={{ filter: `drop-shadow(0 0 5px ${accent})` }}>
            <g stroke={accent} strokeWidth="1.5" opacity="0.35">
              <line x1="25" y1="28" x2="50" y2="50" />
              <line x1="75" y1="28" x2="50" y2="50" />
              <line x1="25" y1="72" x2="50" y2="50" />
              <line x1="75" y1="72" x2="50" y2="50" />
              <line x1="25" y1="28" x2="25" y2="72" />
              <line x1="75" y1="28" x2="75" y2="72" />
              <line x1="50" y1="50" x2="50" y2="14" />
            </g>
            {[[50,14],[25,28],[75,28],[50,50],[25,72],[75,72]].map(([x,y],i) => (
              <circle key={i} cx={x} cy={y} r="4.5" fill={accent}
                style={{ animation: `nnPulse 2.4s ease-in-out infinite ${i*0.25}s` }} />
            ))}
          </svg>
        </div>
        
        {/* State/Model Info */}
        <div className="flex-1 flex flex-col gap-2 tp-3">
          <div className="flex justify-between border-b border-sgc-border pb-1">
            <span>Model</span>
            <span className="text-sgc-bright text-right">gemma3:12b</span>
          </div>
          <div className="flex justify-between border-b border-sgc-border pb-1">
            <span>Context Window</span>
            <span className="text-sgc-bright">8.2K / 32K</span>
          </div>
          <div className="flex justify-between border-b border-sgc-border pb-1">
            <span>Confidence</span>
            <div className="flex items-center gap-2">
              <div className="w-16 h-1 bg-[#0a1526] rounded-full overflow-hidden border border-sgc-border">
                <div className={cn("h-full transition-all duration-500", isExecuting ? "bg-[#00ff41]" : "bg-sgc-primary")} style={{ width: '89%' }} />
              </div>
              <span className="text-sgc-bright">89%</span>
            </div>
          </div>
          <div className="flex justify-between border-b border-sgc-border pb-1">
            <span>Active Agent</span>
            <span className={cn("drop-shadow-[0_0_5px_#00f3ff] transition-colors", isExecuting ? "text-[#00ff41]" : "text-sgc-primary")}>{status.currentAgent || 'Onyx-Core'}</span>
          </div>
        </div>
      </div>

      {/* Reasoning state as requested */}
      <div className="font-mono text-[10px] uppercase tracking-widest text-sgc-dim border-t border-sgc-border pt-3">
        <div className="mb-2">Reasoning Engine</div>
        <div className="grid grid-cols-5 gap-1 text-center">
          <div className={cn("border py-1 rounded transition-colors duration-300", isIdle ? "bg-sgc-primary/20 border-sgc-border-bright text-sgc-border-bright shadow-[0_0_8px_rgba(0,243,255,0.3)]" : "bg-[#0a1526] border-sgc-border")}>IDLE</div>
          <div className={cn("border py-1 rounded transition-colors duration-300", isThinking ? "bg-purple-500/20 border-purple-400 text-purple-400 shadow-[0_0_8px_rgba(168,85,247,0.3)]" : "bg-[#0a1526] border-sgc-border")}>THINK</div>
          <div className={cn("border py-1 rounded transition-colors duration-300", isPlanning ? "bg-blue-500/20 border-blue-400 text-blue-400 shadow-[0_0_8px_rgba(59,130,246,0.3)]" : "bg-[#0a1526] border-sgc-border")}>PLAN</div>
          <div className={cn("border py-1 rounded transition-colors duration-300", isExecuting ? "bg-[#00ff41]/20 border-[#00ff41] text-[#00ff41] shadow-[0_0_8px_rgba(0,255,65,0.3)]" : "bg-[#0a1526] border-sgc-border")}>EXEC</div>
          <div className={cn("border py-1 rounded transition-colors duration-300", isWaiting ? "bg-yellow-500/20 border-yellow-400 text-yellow-400 shadow-[0_0_8px_rgba(234,179,8,0.3)]" : "bg-[#0a1526] border-sgc-border")}>WAIT</div>
        </div>
      </div>
    </div>
  )
}
