import type { AssistantStatus } from '@/hooks/useWebSocket'
import { Mic, Bot } from 'lucide-react'
import { motion } from 'framer-motion'

interface Props {
  status: AssistantStatus
}

export function LiveTranscriptionWidget({ status }: Props) {
  return (
    <div className="flex flex-col h-full p-4">
      <div className="flex justify-between items-center mb-4 border-b border-sgc-border pb-3 shrink-0">
        <div className="flex items-center gap-2 text-sgc-bright font-mono tracking-widest text-sm">
          <Mic size={16} className="text-sgc-primary" />
          LIVE TRANSCRIPTION
        </div>
        <div className="flex gap-2">
          <select className="bg-[#0a1526] border border-sgc-border text-sgc-dim text-[10px] font-mono outline-none px-2 py-1 rounded">
            <option>English (en)</option>
          </select>
          <button className="border border-sgc-border text-sgc-dim text-[10px] px-3 py-1 rounded font-mono hover:text-sgc-primary hover:border-sgc-border-bright transition-colors">
            CLEAR
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar flex flex-col gap-6 pr-2">
        {/* User Message */}
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2 font-mono text-[10px] text-[#00ff41] tracking-widest mb-1">
            <Mic size={12} />
            YOU (10:24:15 PM)
          </div>
          <p className="text-sgc-bright text-sm leading-relaxed pl-5 font-sans">
            Read the sign in front of me.
          </p>
        </div>

        {/* Assistant Message */}
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2 font-mono text-[10px] text-sgc-primary tracking-widest mb-1">
            <Bot size={12} />
            SG CUBE (10:24:18 PM)
          </div>
          <p className="text-sgc-bright text-sm leading-relaxed pl-5 font-sans">
            I found a pedestrian crossing sign ahead. The road is clear. You can cross safely.
          </p>
        </div>
        
        {/* Status Indicator */}
        <div className="mt-auto pl-5">
          <div className="flex items-center gap-2 font-mono text-[10px] text-sgc-dim italic">
            <Bot size={12} />
            {status.thinking ? (
              <span className="flex items-center gap-2">
                AI is thinking
                <motion.span
                  animate={{ opacity: [0.2, 1, 0.2] }}
                  transition={{ duration: 1.5, repeat: Infinity }}
                >
                  ...
                </motion.span>
              </span>
            ) : status.listening ? (
              <span className="text-[#00ff41]">Listening...</span>
            ) : (
              <span>Waiting for input...</span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
