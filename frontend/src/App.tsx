import { Routes, Route } from 'react-router-dom'
import { useWebSocket } from './hooks/useWebSocket'
import { Sidebar } from './components/Sidebar'
import { StatusPanel } from './components/StatusPanel'
import { Header } from './components/Header'
import { Footer } from './components/Footer'
import { Dashboard } from './pages/Dashboard'
import { Chat } from './pages/Chat'
import { Voice } from './pages/Voice'
import { Vision } from './pages/Vision'
import { Memory } from './pages/Memory'
import { Agents } from './pages/Agents'
import { Files } from './pages/Files'
import { Settings } from './pages/Settings'
import './App.css'

function App() {
  const { status } = useWebSocket()

  return (
    <div className="app-shell">
      <div className="app-frame">
        <Header />
        <div className="app-body">
          <Sidebar />
          <main className="main-content">
            <Routes>
              <Route path="/" element={<Dashboard status={status} />} />
              <Route path="/chat" element={<Chat status={status} />} />
              <Route path="/voice" element={<Voice status={status} />} />
              <Route path="/vision" element={<Vision />} />
              <Route path="/memory" element={<Memory />} />
              <Route path="/agents" element={<Agents status={status} />} />
              <Route path="/files" element={<Files />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </main>
          <StatusPanel status={status} />
        </div>
        <Footer />
        <div className="frame-corner top-left"></div>
        <div className="frame-corner top-right"></div>
        <div className="frame-corner bottom-left"></div>
        <div className="frame-corner bottom-right"></div>
      </div>
    </div>
  )
}

export default App
