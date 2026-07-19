import { Header } from "@/components/Header";
import { BottomBar } from "@/components/BottomBar";
import { Panel } from "@/components/Panel";
import { CubeVisualization } from "@/components/CubeVisualization";
import { AppBackground } from "@/components/AppBackground";
import { AICorePanel, AICoreStatusPill } from "@/components/AICorePanel";
import { ErrorBoundary } from "@/components/ErrorBoundary";

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
            <Placeholder label="mic viz · waveform · wake word · sensitivity" />
          </Panel>
          <Panel title="Voice Controls" className="flex-1">
            <Placeholder label="mute · pause · settings · history" />
          </Panel>
          <Panel title="Module Status" className="flex-1">
            <Placeholder label="status · model · language · input · noise filter" />
          </Panel>
        </div>

        {/* CENTER COLUMN */}
        <div className="flex flex-col gap-3 min-h-0">
          <Panel title="Live Transcription" className="flex-[2]">
            <Placeholder label="live transcript stream" />
          </Panel>

          <div className="grid grid-cols-[200px_minmax(0,1fr)_200px] gap-3 flex-1">
            <Panel title="Confidence">
              <Placeholder label="89%" />
            </Panel>
            <Panel bodyClassName="p-0 h-full">
              <CubeVisualization />
            </Panel>
            <div className="flex flex-col gap-3">
              <Panel title="Response Mode" className="flex-1">
                <Placeholder label="LOCAL-FIRST" />
              </Panel>
              <Panel title="Latency" className="flex-1">
                <Placeholder label="12 ms" />
              </Panel>
            </div>
          </div>

          <div className="grid grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] gap-3 flex-1">
            <Panel title="Activity Timeline">
              <Placeholder label="event stream" />
            </Panel>
            <Panel title="Quick Actions">
              <Placeholder label="web search · screen reader · file manager · open apps · take note · calculator" />
            </Panel>
          </div>
        </div>

        {/* RIGHT COLUMN */}
        <div className="flex flex-col gap-3 min-h-0">
          <Panel title="AI Core" number="01" statusSlot={<AICoreStatusPill />}>
            <AICorePanel />
          </Panel>
          <Panel title="Memory Engine" number="02" status="Optimized" statusTone="success">
            <Placeholder label="vector db · entries · recall · score" />
          </Panel>
          <Panel title="Vision Module" number="03" status="Standby" statusTone="warning">
            <Placeholder label="camera · object detection · OCR · scene · navigation" />
          </Panel>
          <Panel title="SG-Cube Architecture" className="flex-1">
            <Placeholder label="voice · ai core · memory · vision · tools" />
          </Panel>
        </div>
      </main>
      </ErrorBoundary>

        <BottomBar />
      </div>
    </div>
  );
}

function Placeholder({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-full min-h-16 text-hud-text-muted text-xs uppercase tracking-widest font-mono">
      {label}
    </div>
  );
}
