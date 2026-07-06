import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/utils'
import {
  LayoutDashboard, MessageSquare, Database, Bot, FileText, Settings, Power
} from 'lucide-react'

const links = [
  { to: "/", icon: LayoutDashboard, title: "Dashboard" },
  { to: "/chat", icon: MessageSquare, title: "Chat" },
  { to: "/memory", icon: Database, title: "Memory" },
  { to: "/agents", icon: Bot, title: "Agents" },
  { to: "/files", icon: FileText, title: "Files" },
  { to: "/settings", icon: Settings, title: "Settings" },
]

export function Sidebar() {
  return (
    <aside className="w-[50px] border-r border-sgc-border-bright flex flex-col items-center py-5 gap-6 bg-[rgba(0,229,255,0.02)]">
      <nav className="flex flex-col items-center gap-6">
        {links.map(({ to, icon: Icon, title }) => (
          <NavLink
            key={to}
            to={to}
            title={title}
            className={({ isActive }) =>
              cn(
                "text-sgc-dim transition-all duration-200",
                isActive
                  ? "text-sgc-border-bright drop-shadow-[0_0_5px_#00f3ff]"
                  : "hover:text-sgc-border-bright hover:drop-shadow-[0_0_5px_#00f3ff]"
              )
            }
          >
            <Icon size={20} />
          </NavLink>
        ))}
      </nav>
      <div className="mt-auto">
        <button className="text-sgc-dim hover:text-sgc-danger transition-colors" title="Power">
          <Power size={20} />
        </button>
      </div>
    </aside>
  )
}
