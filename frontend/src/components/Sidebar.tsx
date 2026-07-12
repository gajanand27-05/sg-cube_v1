import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/utils'
import {
  Mic, Camera, Brain, FolderOpen, Globe, Settings, Plus, LayoutDashboard
} from 'lucide-react'

const links = [
  { to: "/", icon: LayoutDashboard, title: "Home" },
  { to: "/chat", icon: Mic, title: "Voice" },
  { to: "/canvas", icon: Camera, title: "Vision" },
  { to: "/memory", icon: Brain, title: "Memory" },
  { to: "/files", icon: FolderOpen, title: "Files" },
  { to: "/agents", icon: Globe, title: "Network" },
]

export function Sidebar() {
  return (
    <aside className="w-16 border-r border-sgc-border flex flex-col items-center py-6 gap-6 bg-sgc-panel shrink-0">
      <nav className="flex flex-col items-center gap-6">
        {links.map(({ to, icon: Icon, title }) => (
          <NavLink
            key={to}
            to={to}
            title={title}
            className={({ isActive }) =>
              cn(
                "p-3 rounded-xl transition-all duration-300 relative group",
                isActive
                  ? "bg-[#0a1526] text-sgc-primary shadow-[0_0_15px_rgba(0,243,255,0.2)] border border-sgc-border-bright"
                  : "text-sgc-dim hover:text-sgc-primary hover:bg-[#0a1526] hover:shadow-[0_0_15px_rgba(0,243,255,0.1)] border border-transparent"
              )
            }
          >
            <Icon size={20} className="relative z-10" />
            {/* Subtle glow underneath active icon */}
            <div className={cn(
              "absolute inset-0 rounded-xl bg-sgc-primary opacity-0 blur-md transition-opacity duration-300 -z-0",
              "group-[.active]:opacity-20"
            )} />
          </NavLink>
        ))}
      </nav>
      
      <div className="mt-auto flex flex-col items-center gap-6">
        <button className="p-3 rounded-xl text-sgc-dim hover:text-sgc-primary hover:bg-[#0a1526] transition-all border border-transparent hover:border-sgc-border-bright" title="Settings">
          <Settings size={20} />
        </button>
        <button className="w-10 h-10 rounded-full flex items-center justify-center bg-sgc-primary text-[#0a101f] shadow-[0_0_15px_rgba(0,243,255,0.4)] hover:shadow-[0_0_25px_rgba(0,243,255,0.6)] transition-all" title="New Action">
          <Plus size={24} />
        </button>
      </div>
    </aside>
  )
}
