import type { AssistantStatus } from '@/hooks/useWebSocket'
import { cn } from '@/utils/cn'

interface Props {
  status: AssistantStatus
}

export function CubeCoreWidget({ status }: Props) {
  const isListening = status.listening
  const isThinking = status.thinking
  const isExecuting = status.state === 'executing' || status.state === 'calling_tool'
  const isSpeaking = status.speaking

  // State colour drives the whole stage (rings, bloom, platform, particles).
  const accent = isThinking
    ? '#a855f7'
    : isExecuting
      ? '#00ff41'
      : isListening
        ? '#00f3ff'
        : '#00f3ff'

  const faceClass = isThinking
    ? "border-purple-500 shadow-[0_0_30px_rgba(168,85,247,0.4),inset_0_0_30px_rgba(168,85,247,0.4)] bg-[rgba(168,85,247,0.1)] text-purple-400"
    : isExecuting
      ? "border-[#00ff41] shadow-[0_0_30px_rgba(0,255,65,0.4),inset_0_0_30px_rgba(0,255,65,0.4)] bg-[rgba(0,255,65,0.1)] text-[#00ff41]"
      : "border-sgc-border-bright shadow-[0_0_20px_rgba(0,243,255,0.3),inset_0_0_20px_rgba(0,243,255,0.3)] bg-[rgba(0,243,255,0.05)] text-sgc-border-bright"

  return (
    <div
      className="flex-1 w-full h-full relative overflow-hidden flex items-center justify-center p-4"
      style={{ ['--cube-accent' as string]: accent }}
    >
      {/* Ambient bloom behind the core */}
      <div className="cube-bloom" />

      {/* Light rays */}
      <div
        className="absolute w-[520px] h-[520px] opacity-30 pointer-events-none"
        style={{
          background: `conic-gradient(from 0deg, transparent 0deg, ${accent}22 8deg, transparent 16deg, transparent 180deg, ${accent}22 188deg, transparent 196deg, transparent 360deg)`,
          maskImage: 'radial-gradient(circle, black 30%, transparent 70%)',
          WebkitMaskImage: 'radial-gradient(circle, black 30%, transparent 70%)',
        }}
      />

      {/* Concentric orbit rings with travelling particles */}
      <div className="orbit-ring w-[200px] h-[200px] animate-spin-slow" style={{ borderColor: `${accent}22` }}>
        <span className="orbit-particle !w-2 !h-2" />
      </div>
      <div className="orbit-ring w-[280px] h-[280px]" style={{ borderColor: `${accent}18`, animation: 'spin-slow 14s linear infinite reverse' }}>
        <span className="orbit-particle" />
      </div>
      <div className="orbit-ring w-[360px] h-[360px]" style={{ borderColor: `${accent}14`, animation: 'spin-slow 20s linear infinite' }}>
        <span className="orbit-particle !w-1.5 !h-1.5" />
      </div>

      {/* Background grid circles */}
      <svg viewBox="0 0 500 500" className={cn("absolute w-[120%] h-[120%] max-w-[500px] max-h-[500px] opacity-40 pointer-events-none transition-all duration-700", isListening ? "scale-110 opacity-60" : "scale-100")} preserveAspectRatio="xMidYMid meet">
        <circle cx="250" cy="250" r="230" fill="none" stroke="var(--sgc-dim)" strokeWidth="1" opacity="0.3" strokeDasharray="1 10" className="animate-spin-slow origin-center" />
        <circle cx="250" cy="250" r="220" fill="none" stroke="var(--sgc-border-bright)" strokeWidth="1" opacity="0.2" strokeDasharray="5 15" />
        <circle cx="250" cy="250" r="200" fill="none" stroke="var(--sgc-border-bright)" strokeWidth="4" opacity="0.4" strokeDasharray="2 6" className={cn("origin-center transition-all duration-1000", isThinking ? "animate-spin" : "animate-spin-slow")} style={{ animationDirection: 'reverse' }} />
        <circle cx="250" cy="250" r="200" fill="none" stroke="var(--sgc-border-bright)" strokeWidth="1" opacity="0.3" />
        <circle cx="250" cy="250" r="180" fill="none" stroke={isThinking ? "#a855f7" : "var(--sgc-border-bright)"} strokeWidth="2" opacity={isThinking ? 0.4 : 0.1} className="transition-colors duration-500" />
        <circle cx="250" cy="250" r="175" fill="none" stroke="var(--sgc-bright)" strokeWidth="1" opacity="0.3" strokeDasharray="20 40" className="animate-spin-slow origin-center" />
        <circle cx="250" cy="250" r="150" fill="none" stroke={isExecuting ? "#00ff41" : "var(--sgc-border-bright)"} strokeWidth="3" opacity={isExecuting ? 1 : 0.8} strokeDasharray={isExecuting ? "20 10" : "80 20 10 20 40 20"} className={cn("origin-center transition-all duration-500", isExecuting ? "animate-spin" : "animate-spin-slow")} />

        {isListening && (
          <>
            <circle cx="250" cy="250" r="120" fill="none" stroke="var(--sgc-border-bright)" strokeWidth="2" className="animate-ping opacity-20 origin-center" />
            <circle cx="250" cy="250" r="80" fill="none" stroke="var(--sgc-border-bright)" strokeWidth="4" className="animate-ping opacity-10 origin-center" style={{ animationDelay: '200ms' }} />
          </>
        )}

        <line x1="250" y1="0" x2="250" y2="30" stroke="var(--sgc-border-bright)" strokeWidth="2" opacity="0.8" />
        <line x1="250" y1="470" x2="250" y2="500" stroke="var(--sgc-border-bright)" strokeWidth="2" opacity="0.8" />
        <line x1="0" y1="250" x2="30" y2="250" stroke="var(--sgc-border-bright)" strokeWidth="2" opacity="0.8" />
        <line x1="470" y1="250" x2="500" y2="250" stroke="var(--sgc-border-bright)" strokeWidth="2" opacity="0.8" />
      </svg>

      {/* Glowing platform under the cube */}
      <div className="cube-platform" />

      <div className="absolute top-4 left-4 font-mono">
        <div className="tp-1">SG CUBE CORE</div>
        <div className="text-sgc-dim text-[10px] uppercase tracking-wider mt-1">Intelligence Hub</div>
      </div>

      <div className="absolute bottom-4 font-mono text-[10px] tracking-widest uppercase">
        <div className="bg-[#0a1526] border border-sgc-border px-4 py-1.5 rounded-full text-[#00ff41] shadow-[0_0_10px_rgba(0,255,65,0.2)] transition-colors duration-300">
          System Status: Operational
        </div>
      </div>

      {/* The cube itself */}
      <div className="absolute flex flex-col items-center justify-center z-10" style={{ perspective: '1200px', transform: 'scale(0.9)' }}>
        <div className="cube-container">
          <div className={cn("cube transition-all duration-700", isThinking ? "animate-cube-rotate-fast" : isSpeaking ? "animate-pulse" : "animate-cube-rotate")}>
            {['front', 'right', 'back', 'left', 'top', 'bottom'].map((face) => (
              <div
                key={face}
                className={cn(
                  `face ${face} border flex items-center justify-center font-bold text-2xl tracking-[4px] transition-all duration-500`,
                  faceClass
                )}
              >
                SG
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
