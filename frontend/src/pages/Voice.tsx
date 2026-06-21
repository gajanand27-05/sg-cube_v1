import { useState, useRef } from 'react'
import { motion } from 'framer-motion'
import { Mic, Square } from 'lucide-react'
import type { AssistantStatus } from '@/hooks/useWebSocket'

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
    <div className="h-full flex flex-col p-4">
      <div className="flex items-baseline gap-3 mb-4 shrink-0">
        <h1 className="font-sans font-bold text-2xl tracking-[2px] text-sgc-primary m-0">Voice</h1>
        <span className="font-mono text-[11px] text-sgc-dim tracking-wider">Voice Input & Output</span>
      </div>
      <div className="flex-1 flex flex-col items-center justify-center gap-6">
        <motion.button
          className={`w-40 h-40 rounded-full border-2 flex items-center justify-center font-sans text-sm font-semibold cursor-pointer transition-all ${
            recording
              ? 'border-sgc-danger text-sgc-danger shadow-[0_0_30px_rgba(255,0,60,0.3)]'
              : 'border-sgc-border text-sgc-primary hover:border-sgc-border-bright hover:shadow-[0_0_20px_rgba(0,243,255,0.2)]'
          }`}
          onClick={recording ? stopRecording : startRecording}
          animate={recording ? { scale: [1, 1.05, 1] } : {}}
          transition={{ duration: 1.5, repeat: Infinity }}
        >
          {recording ? <Square size={24} /> : <Mic size={24} />}
        </motion.button>
        {status.listening && (
          <div className="font-mono text-sm text-sgc-warn animate-blink">Wake word detected — listening...</div>
        )}
        {transcript && (
          <div className="w-full max-w-lg">
            <div className="font-mono text-[10px] text-sgc-dim tracking-wider mb-1">Transcript</div>
            <div className="font-mono text-sm text-sgc-bright px-3.5 py-2.5 border border-sgc-border bg-[rgba(0,243,255,0.05)]">
              {transcript}
            </div>
          </div>
        )}
        {response && (
          <div className="w-full max-w-lg">
            <div className="font-mono text-[10px] text-sgc-dim tracking-wider mb-1">Response</div>
            <div className="font-mono text-sm text-sgc-bright px-3.5 py-2.5 border border-sgc-border bg-[rgba(0,243,255,0.05)]">
              {response}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
