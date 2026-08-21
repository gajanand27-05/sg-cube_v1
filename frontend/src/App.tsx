import { Header } from "@/components/Header";
import { BottomBar } from "@/components/BottomBar";
import { Panel } from "@/components/Panel";
import { CubeVisualization } from "@/components/CubeVisualization";
import { AppBackground } from "@/components/AppBackground";
import { AICorePanel, AICoreStatusPill } from "@/components/AICorePanel";
import {
  MemoryEnginePanel,
  MemoryEngineStatusPill,
} from "@/components/MemoryEnginePanel";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { LiveTranscriptionPanel } from "@/components/LiveTranscriptionPanel";
import { ConfidencePanel } from "@/components/ConfidencePanel";
import { ActivityTimelinePanel } from "@/components/ActivityTimelinePanel";
import { VoiceModulePanel } from "@/components/VoiceModulePanel";
import { VoiceControlsPanel } from "@/components/VoiceControlsPanel";
import { ModuleStatusPanel } from "@/components/ModuleStatusPanel";
import { QuickActionsPanel } from "@/components/QuickActionsPanel";
import { ResponseModePanel } from "@/components/ResponseModePanel";
import { ArchitectureSection } from "@/components/ArchitecturePanel";
import { SystemStatsPanel } from "@/components/SystemStatsPanel";

export default function App() {
  return (
    <div className="min-h-screen flex flex-col relative">
      <AppBackground />
      <div className="relative z-10 flex flex-col flex-1 min-h-0">
        <Header />

      <ErrorBoundary>
      <main className="flex-1 grid gap-3 p-3 grid-cols-[340px_minmax(0,1fr)_340px]">
        {/* LEFT COLUMN */}
        <div className="flex flex-col gap-3 min-h-0">
          <Panel title="Voice Module" className="flex-[2]">
            <VoiceModulePanel />
          </Panel>
          <Panel title="Voice Controls" className="flex-1">
            <VoiceControlsPanel />
          </Panel>
          <Panel title="Module Status" className="flex-1">
            <ModuleStatusPanel />
          </Panel>
        </div>

        {/* CENTER COLUMN */}
        <div className="flex flex-col gap-3 min-h-0">
          {/* Fixed-height body: this panel used to be flex-[2] and absorbed all
              the column's slack, ballooning to ~490px of mostly empty space.
              220px comfortably fits the You/Onyx pair at 3+ lines each; longer
              content scrolls inside the lanes (bottom-follow). */}
          <Panel title="Live Transcription" bodyClassName="p-4 h-[220px]">
            <LiveTranscriptionPanel />
          </Panel>

          <div className="grid grid-cols-[200px_minmax(0,1fr)_200px] gap-3 flex-1">
            <Panel title="Confidence">
              <ConfidencePanel />
            </Panel>
            <Panel bodyClassName="p-0 h-full">
              <CubeVisualization />
            </Panel>
            <div className="flex flex-col gap-3">
              <Panel title="Response Mode" className="flex-1">
                <ResponseModePanel />
              </Panel>
              <Panel title="System" className="flex-1">
                <SystemStatsPanel />
              </Panel>
            </div>
          </div>

          <div className="grid grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] gap-3 flex-1">
            <Panel title="Activity Timeline" bodyClassName="p-4 h-full">
              <ActivityTimelinePanel />
            </Panel>
            <Panel title="Quick Actions">
              <QuickActionsPanel />
            </Panel>
          </div>
        </div>

        {/* RIGHT COLUMN */}
        <div className="flex flex-col gap-3 min-h-0">
          <Panel title="AI Core" number="01" statusSlot={<AICoreStatusPill />}>
            <AICorePanel />
          </Panel>
          <Panel
            title="Memory Engine"
            number="02"
            statusSlot={<MemoryEngineStatusPill />}
          >
            <MemoryEnginePanel />
          </Panel>
          <ArchitectureSection />
        </div>
      </main>
      </ErrorBoundary>

        <BottomBar />
      </div>
    </div>
  );
}


