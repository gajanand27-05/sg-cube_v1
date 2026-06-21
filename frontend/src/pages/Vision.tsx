import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function Vision() {
  const [screenshot, setScreenshot] = useState<string | null>(null)
  const [lastUpdate, setLastUpdate] = useState<string>('')

  const refreshScreenshot = async () => {
    try {
      const res = await fetch('/vision/screenshot', { credentials: 'include' })
      if (!res.ok) return
      const blob = await res.blob()
      setScreenshot(URL.createObjectURL(blob))
      setLastUpdate(new Date().toLocaleTimeString())
    } catch { /* ignore */ }
  }

  useEffect(() => {
    refreshScreenshot()
    const interval = setInterval(refreshScreenshot, 5000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="h-full flex flex-col p-4">
      <div className="flex items-baseline gap-3 mb-4 shrink-0">
        <h1 className="font-sans font-bold text-2xl tracking-[2px] text-sgc-primary m-0">Vision</h1>
        <span className="font-mono text-[11px] text-sgc-dim tracking-wider">Screen Awareness</span>
        <Button variant="ghost" size="sm" onClick={refreshScreenshot} className="ml-auto">
          <RefreshCw size={14} className="mr-1" /> Refresh
        </Button>
      </div>
      <motion.div
        className="flex-1 flex flex-col items-center gap-3"
        key={screenshot}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
      >
        {screenshot ? (
          <img src={screenshot} alt="Current screen" className="max-w-full max-h-[calc(100vh-200px)] border border-sgc-border shadow-[0_0_20px_rgba(0,243,255,0.1)]" />
        ) : (
          <div className="flex-1 flex items-center justify-center font-mono text-sm text-sgc-dim">No screenshot available</div>
        )}
        {lastUpdate && (
          <div className="font-mono text-[10px] text-sgc-dim">Last capture: {lastUpdate}</div>
        )}
      </motion.div>
    </div>
  )
}
