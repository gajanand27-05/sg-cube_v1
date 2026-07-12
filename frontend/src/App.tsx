import { Routes, Route, Navigate } from 'react-router-dom'
import { useWebSocket } from '@/hooks/useWebSocket'
import { Sidebar } from '@/components/Sidebar'
import { Header } from '@/components/Header'
import { CommandCenter } from '@/pages/CommandCenter'
import { Chat } from '@/pages/Chat'
import { Canvas } from '@/pages/Canvas'
import { Memory } from '@/pages/Memory'
import { Settings } from '@/pages/Settings'
import './App.css'

function App() {
  const { status, events } = useWebSocket()

  return (
    <div className="flex items-center justify-center h-screen w-screen relative">
      {/* Faint background grid + floating particles — atmosphere, sits
          behind the app shell (Layer 2 + Layer 3). */}
      <div className="pointer-events-none fixed inset-0 bg-grid opacity-[0.06] z-0" />
      <div className="pointer-events-none fixed inset-0 bg-particles opacity-[0.06] z-0" />
      <div className="flex flex-col w-full h-full max-w-[1920px] text-sgc-bright font-sans overflow-hidden relative z-10">
        
        {/* TOP BAR */}
        <Header />

        <div className="flex flex-1 overflow-hidden relative">
          
          {/* SIDEBAR NAVIGATION */}
          <Sidebar />

          {/* MAIN CONTENT AREA — transparent so the body's atmospheric
              gradient + glows show through behind the glass widgets. */}
          <main className="flex-1 relative flex flex-col min-w-0 min-h-0">
            <div className="relative z-10 flex-1 h-full w-full">
              <Routes>
                {/* CommandCenter replaces Dashboard as the root experience */}
                <Route path="/" element={<CommandCenter status={status} events={events} />} />
                <Route path="/chat" element={<Chat status={status} />} />
                <Route path="/memory" element={<Memory />} />
                <Route path="/canvas" element={<Canvas />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </div>
          </main>

        </div>
      </div>
    </div>
  )
}

export default App
