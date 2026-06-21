import { useState, useEffect, useCallback } from 'react'

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
    <div className="page">
      <div className="page-header">
        <h1>Files</h1>
        <span className="page-subtitle">File System Browser</span>
      </div>
      <div className="files-toolbar">
        <button className="files-btn" onClick={() => load(path)} disabled={loading}>
          ↻ Refresh
        </button>
        <span className="files-path">{path}</span>
      </div>
      {error && <div className="files-error">{error}</div>}
      <div className="files-table-header">
        <span className="ft-name">Name</span>
        <span className="ft-size">Size</span>
        <span className="ft-modified">Modified</span>
      </div>
      <div className="files-scroll">
        {path !== '.' && (
          <div className="file-row" onClick={() => load(path + '/..')}>
            <span className="file-icon">📁</span>
            <span className="file-name">..</span>
            <span className="file-size"></span>
            <span className="file-modified"></span>
          </div>
        )}
        {entries.map((e, i) => (
          <div key={i} className="file-row" onClick={() => e.is_dir && load(e.path)}>
            <span className="file-icon">{e.is_dir ? '📁' : '📄'}</span>
            <span className="file-name">{e.name}</span>
            <span className="file-size">{e.is_dir ? '-' : formatSize(e.size)}</span>
            <span className="file-modified">{formatTime(e.modified)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
