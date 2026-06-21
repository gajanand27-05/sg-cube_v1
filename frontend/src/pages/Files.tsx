import { useState, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import { RefreshCw, FolderOpen, File } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface FileEntry {
  name: string
  path: string
  is_dir: boolean
  size: number
  modified: number
}

export function Files() {
  const [path, setPath] = useState('.')
  const [entries, setEntries] = useState<FileEntry[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (dir: string) => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`/files/list?path=${encodeURIComponent(dir)}`, {
        credentials: 'include',
      })
      const data = await res.json()
      if (data.error) {
        setError(data.error)
        setEntries([])
      } else {
        setEntries(data.entries || [])
        setPath(data.path)
      }
    } catch {
      setError('Failed to load directory')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load(path) }, [])

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const formatTime = (ts: number) => {
    const d = new Date(ts * 1000)
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString()
  }

  return (
    <div className="h-full flex flex-col p-4">
      <div className="flex items-baseline gap-3 mb-4 shrink-0">
        <h1 className="font-sans font-bold text-2xl tracking-[2px] text-sgc-primary m-0">Files</h1>
        <span className="font-mono text-[11px] text-sgc-dim tracking-wider">File System Browser</span>
      </div>

      <div className="flex items-center gap-3 mb-2 shrink-0">
        <Button variant="outline" size="sm" onClick={() => load(path)} disabled={loading}>
          <RefreshCw size={14} className="mr-1" /> Refresh
        </Button>
        <span className="font-mono text-xs text-sgc-secondary">{path}</span>
      </div>

      {error && <div className="font-mono text-xs text-sgc-danger mb-2">{error}</div>}

      <div className="grid grid-cols-[28px_1fr_100px_160px] gap-2 px-2 py-1.5 border-b border-sgc-border font-mono text-[10px] text-sgc-dim tracking-wider shrink-0">
        <span />
        <span>Name</span>
        <span>Size</span>
        <span>Modified</span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {path !== '.' && (
          <motion.div
            className="grid grid-cols-[28px_1fr_100px_160px] gap-2 px-2 py-1.5 items-center cursor-pointer border-b border-[rgba(0,243,255,0.05)] hover:bg-[rgba(0,243,255,0.05)]"
            onClick={() => load(path + '/..')}
            whileHover={{ x: 2 }}
          >
            <FolderOpen size={16} className="text-sgc-secondary justify-self-center" />
            <span className="font-mono text-xs text-sgc-bright">..</span>
            <span />
            <span />
          </motion.div>
        )}
        {entries.map((e, i) => (
          <motion.div
            key={i}
            className="grid grid-cols-[28px_1fr_100px_160px] gap-2 px-2 py-1.5 items-center cursor-pointer border-b border-[rgba(0,243,255,0.05)] hover:bg-[rgba(0,243,255,0.05)]"
            onClick={() => e.is_dir && load(e.path)}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: i * 0.01 }}
          >
            {e.is_dir
              ? <FolderOpen size={16} className="text-sgc-secondary justify-self-center" />
              : <File size={16} className="text-sgc-dim justify-self-center" />
            }
            <span className="font-mono text-xs text-sgc-bright">{e.name}</span>
            <span className="font-mono text-[11px] text-sgc-dim">{e.is_dir ? '-' : formatSize(e.size)}</span>
            <span className="font-mono text-[11px] text-sgc-dim">{formatTime(e.modified)}</span>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
