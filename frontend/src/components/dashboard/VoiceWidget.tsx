import { Mic } from 'lucide-react'
import { useChatStore } from '@/store'
import { cn } from '@/lib/utils'

export function VoiceWidget() {
  const listening = useChatStore((s) => s.listening)
  const speaking = useChatStore((s) => s.speaking)
  const lastCommand = useChatStore((s) => s.lastCommand)
  const lastResponse = useChatStore((s) => s.lastResponse)
  const confidence = useChatStore((s) => s.confidence)

  const state = listening ? 'LISTENING' : speaking ? 'SPEAKING' : 'IDLE'

  return (
    <div className="glass rounded-2xl flex flex-col p-5">
      <div className="flex justify-between items-center mb-6">
        <div className="flex items-center gap-2 tp-1">
          <Mic size={16} className="text-sgc-primary drop-shadow-[0_0_8px_rgba(0,243,255,0.35)]" />
          VOICE MODULE
        </div>
        <div className={cn(
          "text-[10px] px-2 py-0.5 rounded font-mono border tracking-widest",
          listening
            ? "bg-[#00ff41]/20 text-[#00ff41] shadow-[0_0_8px_rgba(0,255,65,0.4)] border-[#00ff41]/50"
            : "bg-[#0a1526] text-sgc-dim border-sgc-border"
        )}>
          {state}
        </div>
      </div>

      {/* Center Mic Graphic */}
      <div className="flex justify-center my-4 relative">
        <div className="absolute inset-0 flex items-center justify-center">
          {listening && (
            <>
              <div className="w-24 h-24 rounded-full border border-sgc-border-bright opacity-20 animate-ping" />
              <div className="absolute w-32 h-32 rounded-full border border-sgc-border-bright opacity-10 animate-pulse" />
            </>
          )}
        </div>
        <div className={cn(
          "w-16 h-16 rounded-full bg-[#0a1526] border-2 flex items-center justify-center z-10 transition-all duration-300",
          listening
            ? "border-sgc-primary shadow-[0_0_20px_rgba(0,243,255,0.5)]"
            : "border-sgc-border-bright shadow-[0_0_20px_rgba(0,243,255,0.4)]"
        )}>
          <Mic size={28} className={cn(
            "transition-colors duration-300",
            listening ? "text-sgc-primary drop-shadow-[0_0_8px_rgba(0,243,255,0.35)]" : "text-sgc-dim"
          )} />
        </div>
      </div>

      {/* Equalizer — activity indicator while listening (not real amplitude) */}
      <div className="flex items-end justify-center gap-1 h-12 mb-8">
        {[...Array(20)].map((_, i) => (
          <div
            key={i}
            className={cn("w-1 bg-sgc-primary rounded-t transition-all", listening && "animate-pulse")}
            style={{
              height: listening ? `${20 + ((i * 37) % 70)}%` : '18%',
              opacity: listening ? 0.85 : 0.3,
              animationDelay: `${i * 0.08}s`,
            }}
          />
        ))}
      </div>

      <div className="flex flex-col gap-5 mt-auto">
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-sgc-dim uppercase tracking-wider">Last Command</span>
          <span className="text-sgc-bright text-sm tracking-wide truncate">
            {lastCommand || 'Awaiting voice…'}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-5 tp-3 mt-2">
          <div className="flex justify-between border-b border-sgc-border pb-1">
            <span>Confidence</span>
            <span className="text-sgc-bright">{confidence.toFixed(1)}%</span>
          </div>
          <div className="flex justify-between border-b border-sgc-border pb-1">
            <span>State</span>
            <span className={listening ? "text-[#00ff41]" : "text-sgc-bright"}>{state}</span>
          </div>
          <div className="flex justify-between border-b border-sgc-border pb-1 col-span-2">
            <span>Last Response</span>
            <span className="text-sgc-bright truncate text-right max-w-[65%]">
              {lastResponse ? (lastResponse.length > 30 ? lastResponse.slice(0, 30) + '…' : lastResponse) : '—'}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
