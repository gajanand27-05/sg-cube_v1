import { motion } from 'framer-motion'

export function Header() {
  return (
    <header className="flex justify-between items-center h-10 border-b border-sgc-border-bright px-4 bg-[rgba(0,243,255,0.05)] shadow-[0_2px_10px_rgba(0,243,255,0.1)]">
      <div className="flex items-center gap-5">
        <div className="[clip-path:polygon(0_0,100%_0,80%_100%,0%_100%)] bg-sgc-border-bright p-[2px]">
          <div className="[clip-path:polygon(0_0,100%_0,80%_100%,0%_100%)] bg-black flex gap-2 px-3 py-2">
            <span className="w-2.5 h-2.5 rounded-full bg-sgc-danger shadow-[0_0_6px_#ff003c]" />
            <span className="w-2.5 h-2.5 rounded-full bg-sgc-warn shadow-[0_0_6px_#ffb700]" />
            <span className="w-2.5 h-2.5 rounded-full bg-[#00ff41] shadow-[0_0_6px_#00ff41]" />
          </div>
        </div>
        <span className="font-mono font-bold text-sm text-sgc-border-bright tracking-[2px] drop-shadow-[0_0_8px_#00f3ff]">
          SG_CUBE v2.0
        </span>
        <span className="font-mono text-[10px] text-sgc-dim tracking-wider ml-3">
          AI Operating System
        </span>
      </div>
      <div className="flex items-center gap-2">
        <motion.span
          className="w-2 h-2 rounded-full bg-[#00ff41] shadow-[0_0_8px_#00ff41]"
          animate={{ opacity: [1, 0, 1] }}
          transition={{ duration: 2, repeat: Infinity }}
        />
        <span className="font-mono text-[11px] text-[#00ff41] tracking-[2px] drop-shadow-[0_0_8px_#00ff41]">
          ONYX ONLINE
        </span>
      </div>
    </header>
  )
}
