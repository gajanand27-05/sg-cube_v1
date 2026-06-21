import { Routes, Route } from 'react-router-dom'
import { useWebSocket } from '@/hooks/useWebSocket'
import { Sidebar } from '@/components/Sidebar'
import { StatusPanel } from '@/components/StatusPanel'
import { Header } from '@/components/Header'
import { Footer } from '@/components/Footer'
import { Dashboard } from '@/pages/Dashboard'
import { Chat } from '@/pages/Chat'
import { Voice } from '@/pages/Voice'
import { Vision } from '@/pages/Vision'
import { Memory } from '@/pages/Memory'
import { Agents } from '@/pages/Agents'
import { Files } from '@/pages/Files'
import { Settings } from '@/pages/Settings'
import './App.css'

function App() {
  const { status, systemStats, events } = useWebSocket()

  return (
    <div className="flex items-center justify-center h-screen w-screen p-4 box-border">
      <div className="flex flex-col w-full h-full border border-sgc-border-bright shadow-[0_0_15px_rgba(0,243,255,0.2),inset_0_0_30px_rgba(0,243,255,0.1),0_0_20px_rgba(0,243,255,0.1)] relative bg-[radial-gradient(circle_at_center,rgba(2,10,20,0.9)_0%,#000_100%)]">
        <span className="absolute w-5 h-5 border-2 border-sgc-border-bright border-r-0 border-b-0 pointer-events-none -top-[2px] -left-[2px]" />
        <span className="absolute w-5 h-5 border-2 border-sgc-border-bright border-l-0 border-b-0 pointer-events-none -top-[2px] -right-[2px]" />
        <span className="absolute w-5 h-5 border-2 border-sgc-border-bright border-r-0 border-t-0 pointer-events-none -bottom-[2px] -left-[2px]" />
        <span className="absolute w-5 h-5 border-2 border-sgc-border-bright border-l-0 border-t-0 pointer-events-none -bottom-[2px] -right-[2px]" />

        <Header />
        <div className="flex flex-1 overflow-hidden">
          <Sidebar />
          <main className="flex-1 overflow-hidden">
            <Routes>
              <Route path="/" element={<Dashboard status={status} systemStats={systemStats} />} />
              <Route path="/chat" element={<Chat status={status} />} />
              <Route path="/voice" element={<Voice status={status} />} />
              <Route path="/vision" element={<Vision />} />
              <Route path="/memory" element={<Memory />} />
              <Route path="/agents" element={<Agents />} />
              <Route path="/files" element={<Files />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </main>
          <StatusPanel status={status} systemStats={systemStats} events={events} />
        </div>
        <Footer systemStats={systemStats} />
      </div>
    </div>
  )
}

export default App
