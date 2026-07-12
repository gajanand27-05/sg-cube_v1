import { useState } from 'react'
import type { AssistantStatus, SystemStats, WsEvent } from '@/hooks/useWebSocket'
import { VoiceWidget } from '@/components/dashboard/VoiceWidget'
import { LiveTranscriptionWidget } from '@/components/dashboard/LiveTranscriptionWidget'
import { CubeCoreWidget } from '@/components/dashboard/CubeCoreWidget'
import { AICoreWidget } from '@/components/dashboard/AICoreWidget'
import { MemoryEngineWidget } from '@/components/dashboard/MemoryEngineWidget'
import { VisionModuleWidget } from '@/components/dashboard/VisionModuleWidget'
import { ArchitectureFlowWidget } from '@/components/dashboard/ArchitectureFlowWidget'
import { MetricsWidget } from '@/components/dashboard/MetricsWidget'
import { EventTimelineWidget } from '@/components/dashboard/EventTimelineWidget'
import { InspectorPanel } from '@/components/dashboard/InspectorPanel'

interface Props {
  status: AssistantStatus
  systemStats?: SystemStats
  events: WsEvent[]
}

export function CommandCenter({ status, events }: Props) {
  const [selectedEvent, setSelectedEvent] = useState<WsEvent | null>(null)

  return (
    <div className="h-full w-full p-5 flex gap-5 overflow-hidden box-border">
      
      {/* LEFT COLUMN: Voice & Quick Actions (30%) */}
      <div className="w-[30%] flex flex-col gap-5 overflow-y-auto pr-1 custom-scrollbar">
        <VoiceWidget />
        <EventTimelineWidget 
          events={events} 
          onSelectEvent={setSelectedEvent} 
          selectedEventId={selectedEvent?.id} 
        />
      </div>

      {/* MIDDLE COLUMN: The Core Experience (40%) */}
      <div className="w-[40%] flex flex-col gap-5 overflow-hidden">
        <div className="flex-1 min-h-0 glass rounded-2xl flex flex-col overflow-hidden relative">
          <LiveTranscriptionWidget status={status} />
        </div>
        <div className="h-[260px] glass rounded-2xl flex flex-col relative overflow-visible shrink-0">
          <CubeCoreWidget status={status} />
        </div>
      </div>

      {/* RIGHT COLUMN: Subsystems & Telemetry or Inspector (30%) */}
      <div className="w-[30%] flex flex-col gap-5 overflow-y-auto pr-1 custom-scrollbar">
        {selectedEvent ? (
          <InspectorPanel 
            event={selectedEvent} 
            onClose={() => setSelectedEvent(null)} 
          />
        ) : (
          <>
            <AICoreWidget status={status} />
            <MemoryEngineWidget />
            <VisionModuleWidget />
            <ArchitectureFlowWidget />
            <MetricsWidget />
          </>
        )}
      </div>

    </div>
  )
}
