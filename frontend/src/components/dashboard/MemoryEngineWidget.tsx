import { Database, Check } from 'lucide-react'

export function MemoryEngineWidget() {
  return (
    <div className="glass rounded-2xl flex flex-col p-4">
      <div className="flex justify-between items-center mb-4 border-b border-sgc-border pb-3">
        <div className="flex items-center gap-2 text-sgc-bright font-mono tracking-widest text-sm">
          <Database size={16} className="text-sgc-primary drop-shadow-[0_0_8px_rgba(0,243,255,0.5)]" />
          MEMORY ENGINE
        </div>
        <div className="flex items-center gap-2">
          {/* Holographic cylinder */}
          <div className="w-7 h-9 relative shrink-0">
            <svg viewBox="0 0 32 40" className="w-full h-full" style={{ filter: 'drop-shadow(0 0 4px rgba(0,255,65,0.5))' }}>
              <ellipse cx="16" cy="8" rx="13" ry="4" fill="none" stroke="#00ff41" strokeOpacity="0.5" />
              <ellipse cx="16" cy="32" rx="13" ry="4" fill="none" stroke="#00ff41" strokeOpacity="0.5" />
              <path d="M3 8 V32 A13 4 0 0 0 29 32 V8" fill="rgba(0,255,65,0.06)" stroke="#00ff41" strokeOpacity="0.4" />
              <circle cx="16" cy="20" r="13" fill="none" stroke="#00ff41" strokeOpacity="0.3" strokeDasharray="3 5"
                style={{ transformOrigin: '16px 20px', animation: 'spin 4s linear infinite' }} />
            </svg>
          </div>
          <div className="text-[#00aaff] text-[10px] font-mono tracking-widest uppercase">
            OPTIMIZED
          </div>
        </div>
      </div>

      {/* Recent Memories List */}
      <div className="flex flex-col gap-2 font-mono text-[10px] uppercase tracking-wider text-sgc-dim mb-4">
        <div className="mb-1 text-sgc-dim">Recent Memories</div>
        <div className="flex flex-col gap-1.5 pl-1">
          <div className="flex items-center gap-2 text-sgc-bright">
            <Check size={12} className="text-[#00ff41]" />
            <span>Office WiFi Password</span>
          </div>
          <div className="flex items-center gap-2 text-sgc-bright">
            <Check size={12} className="text-[#00ff41]" />
            <span>Last Conversation</span>
          </div>
          <div className="flex items-center gap-2 text-sgc-bright">
            <Check size={12} className="text-[#00ff41]" />
            <span>Grocery List</span>
          </div>
          <div className="flex items-center gap-2 text-sgc-bright">
            <Check size={12} className="text-[#00ff41]" />
            <span>Camera Settings</span>
          </div>
        </div>
      </div>

      {/* Working Memory Bar */}
      <div className="mt-2 pt-3 border-t border-sgc-border font-mono text-[10px] uppercase tracking-wider">
        <div className="flex justify-between mb-1.5">
          <span className="text-sgc-dim">Working Memory</span>
          <span className="text-sgc-bright">7 active</span>
        </div>
        <div className="h-2 bg-[#0a1526] rounded-sm overflow-hidden border border-sgc-border flex">
          {[1, 2, 3, 4, 5, 6, 7].map((i) => (
            <div key={i} className="flex-1 bg-[#00aaff] border-r border-[#0a1526] last:border-none opacity-80" />
          ))}
          <div className="flex-[3]" style={{ background: 'repeating-linear-gradient(45deg, transparent, transparent 2px, rgba(0, 170, 255, 0.2) 2px, rgba(0, 170, 255, 0.2) 4px)' }} />
        </div>
      </div>
    </div>
  )
}
