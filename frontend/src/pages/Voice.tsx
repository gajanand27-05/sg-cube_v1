import { useState, useRef } from 'react'
import type { AssistantStatus } from '../hooks/useWebSocket'

interface Props {
  status: AssistantStatus
}

export function Voice({ status }: Props) {
  const [recording, setRecording] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [response, setResponse] = useState('')
  const mediaRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' })
      chunksRef.current = []
      recorder.ondataavailable = (e) => chunksRef.current.push(e.data)
      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
        stream.getTracks().forEach((t) => t.stop())
        await processAudio(blob)
      }
      mediaRef.current = recorder
      recorder.start()
      setRecording(true)
    } catch {
      setTranscript('Microphone access denied')
    }
  }

  const stopRecording = () => {
    mediaRef.current?.stop()
    setRecording(false)
  }

  const processAudio = async (blob: Blob) => {
    const form = new FormData()
    form.append('audio', blob, 'recording.webm')
    try {
      const res = await fetch('/voice/transcribe', {
        method: 'POST',
        credentials: 'include',
        body: form,
      })
      const data = await res.json()
      setTranscript(data.text || '')
      setResponse('Voice command sent to orchestrator')
    } catch {
      setTranscript('Transcription failed')
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1>Voice</h1>
        <span className="page-subtitle">Voice Input & Output</span>
      </div>
      <div className="voice-container">
        <button
          className={`voice-btn ${recording ? 'voice-btn-recording' : ''}`}
          onClick={recording ? stopRecording : startRecording}
        >
          {recording ? '⏹ Stop Recording' : '🎤 Start Recording'}
        </button>
        {status.listening && (
          <div className="voice-listening">Wake word detected — listening...</div>
        )}
        {transcript && (
          <div className="voice-result">
            <div className="voice-result-label">Transcript</div>
            <div className="voice-result-text">{transcript}</div>
          </div>
        )}
        {response && (
          <div className="voice-result">
            <div className="voice-result-label">Response</div>
            <div className="voice-result-text">{response}</div>
          </div>
        )}
      </div>
    </div>
  )
}
