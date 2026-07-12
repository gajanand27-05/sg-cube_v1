import { Network, Mic, Brain, Database, Camera, Wrench, MessageSquare, Lock } from 'lucide-react'
import { motion } from 'framer-motion'

export function ArchitectureFlowWidget() {
  const nodes = [
    { id: 'voice', icon: Mic, label: 'Voice' },
    { id: 'ai', icon: Brain, label: 'AI Core' },
    { id: 'memory', icon: Database, label: 'Memory' },
    { id: 'vision', icon: Camera, label: 'Vision' },
    { id: 'tools', icon: Wrench, label: 'Tools' },
    { id: 'response', icon: MessageSquare, label: 'Response' },
  ]

  return (
    <div className="glass rounded-2xl flex flex-col p-5">
      <div className="flex justify-between items-center mb-4 border-b border-sgc-border pb-3">
        <div className="flex items-center gap-2 tp-1">
          <Network size={16} className="text-sgc-primary drop-shadow-[0_0_8px_rgba(0,243,255,0.35)]" />
          SG-CUBE ARCHITECTURE
        </div>
        <div className="text-sgc-primary text-[10px] font-mono tracking-widest uppercase cursor-pointer hover:text-sgc-bright">
          VIEW DIAGRAM
        </div>
      </div>

      {/* The Flow */}
      <div className="flex items-center justify-between my-4 px-2 relative">
        {/* Connection Line with animated dash */}
        <div className="absolute left-6 right-6 h-0.5 bg-sgc-border top-1/2 -translate-y-1/2 z-0" />
        
        {/* Animated Particles flowing along the line */}
        <div className="absolute left-6 right-6 h-0.5 top-1/2 -translate-y-1/2 overflow-hidden z-0">
           <motion.div
             className="w-full h-full bg-gradient-to-r from-transparent via-[#00f3ff] to-transparent"
             initial={{ x: '-100%' }}
             animate={{ x: '100%' }}
             transition={{ duration: 3, repeat: Infinity, ease: 'linear' }}
             style={{ width: '50%' }}
           />
        </div>

        {nodes.map((node) => (
          <div key={node.id} className="flex flex-col items-center gap-2 z-10">
            <div className="w-8 h-8 rounded-full bg-[#0a1526] border border-sgc-border text-sgc-dim flex items-center justify-center relative shadow-[0_0_10px_rgba(0,10,20,0.8)] hover:border-sgc-border-bright hover:text-sgc-primary transition-colors cursor-default">
              <node.icon size={14} />
            </div>
            <span className="font-mono text-[9px] uppercase tracking-wider text-sgc-dim">{node.label}</span>
          </div>
        ))}
      </div>

      {/* Badges */}
      <div className="mt-4 flex gap-3 font-mono text-[9px] uppercase tracking-wider text-sgc-dim items-center">
        <Lock size={12} className="text-sgc-primary" />
        <span className="text-sgc-bright">DATA FLOW:</span>
        <span className="bg-[#0a1526] border border-sgc-border px-2 py-0.5 rounded text-[#00ff41]">SECURE</span>
        <span className="bg-[#0a1526] border border-sgc-border px-2 py-0.5 rounded text-[#00ff41]">LOCAL-FIRST</span>
        <span className="bg-[#0a1526] border border-sgc-border px-2 py-0.5 rounded text-[#00ff41]">PRIVATE</span>
      </div>
    </div>
  )
}
