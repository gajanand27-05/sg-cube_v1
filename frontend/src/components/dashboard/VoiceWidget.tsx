import { Mic } from 'lucide-react'

export function VoiceWidget() {
  return (
    <div className="glass rounded-2xl flex flex-col p-5">
      <div className="flex justify-between items-center mb-6">
        <div className="flex items-center gap-2 tp-1">
          <Mic size={16} />
          VOICE MODULE
        </div>
        <div className="bg-[#00ff41] bg-opacity-20 text-[#00ff41] text-[10px] px-2 py-0.5 rounded font-mono shadow-[0_0_8px_rgba(0,255,65,0.4)] border border-[#00ff41] border-opacity-50">
          LISTENING...
        </div>
      </div>

      {/* Center Mic Graphic */}
      <div className="flex justify-center my-4 relative">
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-24 h-24 rounded-full border border-sgc-border-bright opacity-20 animate-ping" />
          <div className="absolute w-32 h-32 rounded-full border border-sgc-border-bright opacity-10 animate-pulse" />
        </div>
        <div className="w-16 h-16 rounded-full bg-[#0a1526] border-2 border-sgc-border-bright shadow-[0_0_20px_rgba(0,243,255,0.4)] flex items-center justify-center z-10">
          <Mic size={28} className="text-sgc-primary drop-shadow-[0_0_8px_rgba(0,243,255,0.35)]" />
        </div>
      </div>

      {/* Waveform fake */}
      <div className="flex items-end justify-center gap-1 h-12 mb-8 opacity-70">
        {[...Array(20)].map((_, i) => (
          <div 
            key={i} 
            className="w-1 bg-sgc-primary rounded-t"
            style={{ 
              height: `${Math.max(10, Math.random() * 100)}%`,
              animation: `pulse ${1 + Math.random()}s infinite` 
            }}
          />
        ))}
      </div>

      <div className="flex flex-col gap-5 mt-auto">
        <div className="flex justify-between items-center font-mono">
          <div className="flex flex-col gap-1">
            <span className="text-[10px] text-sgc-dim uppercase tracking-wider">Wake Word</span>
            <span className="text-sgc-bright tracking-widest">"ONYX"</span>
          </div>
          <button className="border border-sgc-border text-sgc-dim text-[10px] px-3 py-1 rounded hover:text-sgc-primary hover:border-sgc-border-bright transition-colors">
            CHANGE
          </button>
        </div>

        <div className="flex flex-col gap-1.5 font-mono">
          <div className="flex justify-between text-[10px] uppercase tracking-wider">
            <span className="text-sgc-dim">Sensitivity</span>
            <span className="text-sgc-bright">75%</span>
          </div>
          <div className="h-1 bg-[#0a1526] rounded-full overflow-hidden border border-sgc-border">
            <div className="h-full bg-sgc-primary w-[75%] shadow-[0_0_8px_rgba(0,243,255,0.6)]" />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-5 tp-3 mt-2">
          <div className="flex justify-between border-b border-sgc-border pb-1">
            <span>Language</span>
            <span className="text-sgc-bright">EN-US</span>
          </div>
          <div className="flex justify-between border-b border-sgc-border pb-1">
            <span>Confidence</span>
            <span className="text-sgc-bright">98.2%</span>
          </div>
          <div className="flex justify-between border-b border-sgc-border pb-1">
            <span>VAD Status</span>
            <span className="text-[#00ff41]">ACTIVE</span>
          </div>
          <div className="flex justify-between border-b border-sgc-border pb-1">
            <span>Timer</span>
            <span className="text-sgc-bright">00:04:12</span>
          </div>
        </div>
      </div>
    </div>
  )
}
