import { useState, useEffect } from 'react'

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
    <div className="page">
      <div className="page-header">
        <h1>Vision</h1>
        <span className="page-subtitle">Screen Awareness</span>
      </div>
      <div className="vision-container">
        {screenshot ? (
          <img src={screenshot} alt="Current screen" className="vision-image" />
        ) : (
          <div className="vision-placeholder">No screenshot available</div>
        )}
        {lastUpdate && (
          <div className="vision-timestamp">Last capture: {lastUpdate}</div>
        )}
      </div>
    </div>
  )
}
