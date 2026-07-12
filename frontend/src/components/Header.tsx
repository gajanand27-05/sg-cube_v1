import { motion } from 'framer-motion'
import { useSocketStore } from '@/store'
import { Bell, User } from 'lucide-react'
import { useEffect, useState } from 'react'

export function Header() {
  const connected = useSocketStore((s) => s.connected)
  const color = connected ? '#00ff41' : '#ff0033'
  
  const [time, setTime] = useState(new Date())
  
  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  return (
    <header className="flex justify-between items-center h-[72px] border-b border-sgc-border px-8 bg-sgc-panel shrink-0">
      
      {/* Left: Logo & Branding */}
      <div className="flex items-center gap-4">
        <div className="w-10 h-10 border border-sgc-border-bright rounded flex items-center justify-center bg-[#0a1526] shadow-[0_0_10px_rgba(0,243,255,0.2)]">
          <span className="font-bold text-sgc-border-bright tracking-widest leading-none">SG</span>
        </div>
        <div className="flex flex-col justify-center">
          <span className="font-bold text-sgc-bright tracking-widest text-lg leading-none">SG CUBE</span>
          <span className="font-mono text-[10px] text-sgc-dim tracking-widest uppercase mt-1">Your AI Assistant</span>
        </div>
      </div>
      
      {/* Center: Command Palette */}
      <div className="flex-1 max-w-xl mx-12 relative group">
        <div className="absolute left-3 top-1/2 -translate-y-1/2 text-sgc-primary drop-shadow-[0_0_5px_rgba(0,243,255,0.5)]">
          <span className="font-mono font-bold">{'>_'}</span>
        </div>
        <input 
          type="text" 
          placeholder="Command Palette (e.g., Open Memory, Enable Camera)" 
          className="w-full bg-[#0a1526] border border-sgc-border rounded py-2 pl-10 pr-10 text-sm font-mono text-sgc-bright outline-none focus:border-sgc-border-bright focus:shadow-[0_0_15px_rgba(0,243,255,0.15)] transition-all placeholder:text-sgc-dim"
        />
        <div className="absolute right-3 top-1/2 -translate-y-1/2 text-sgc-dim border border-sgc-border rounded px-1.5 py-0.5 text-[10px] font-mono group-hover:border-sgc-border-bright group-hover:text-sgc-primary transition-colors">
          /
        </div>
      </div>

      {/* Right: Time, Status, Profile */}
      <div className="flex items-center gap-10">
        
        {/* Time & Date */}
        <div className="flex flex-col items-end justify-center font-mono">
          <span className="text-sgc-bright text-sm tracking-widest">
            {time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </span>
          <span className="text-sgc-dim text-[10px] uppercase tracking-wider">
            {time.toLocaleDateString([], { day: '2-digit', month: 'long', year: 'numeric' })}
          </span>
        </div>
        
        {/* System Status */}
        <div className="flex items-center gap-3 border-l border-sgc-border pl-10">
          <div className="flex flex-col items-end justify-center font-mono">
            <span className="text-sgc-bright text-xs tracking-widest uppercase">{connected ? 'Cloud Connected' : 'Local Mode'}</span>
            <span className="text-sgc-dim text-[10px] tracking-wider">All systems operational</span>
          </div>
          <div className="flex gap-1 h-5 items-end">
            {[1, 2, 3, 4].map((i) => (
              <motion.div 
                key={i}
                className="w-1.5 rounded-t-sm"
                style={{ backgroundColor: color, opacity: connected ? 1 : 0.8 }}
                animate={connected ? { height: ['40%', '100%', '40%'] } : { height: '30%' }}
                transition={{ duration: 1.5, repeat: Infinity, delay: i * 0.2 }}
              />
            ))}
          </div>
        </div>

        {/* Notifications & Profile */}
        <div className="flex items-center gap-5 ml-6">
          <div className="relative cursor-pointer text-sgc-dim hover:text-sgc-bright transition-colors">
            <Bell size={20} />
            <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-sgc-secondary shadow-[0_0_5px_rgba(0,170,255,0.8)]" />
          </div>
          
          <div className="w-8 h-8 rounded-full border border-sgc-border bg-sgc-panel flex items-center justify-center overflow-hidden cursor-pointer hover:border-sgc-border-bright transition-colors">
            <User size={16} className="text-sgc-dim" />
          </div>
        </div>
        
      </div>
    </header>
  )
}
