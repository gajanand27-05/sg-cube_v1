import { useUiConnectionState } from "@/hooks/useUiEvents";
import { Mic, MicOff } from "lucide-react";

/** Voice Controls panel. Shows mute status and connection state. */
export function VoiceControlsPanel() {
  const connection = useUiConnectionState();

  const isMuted = connection !== "open";

  return (
    <div className="flex flex-col gap-4 min-h-0 h-full">
      <div className="flex flex-col gap-2">
        <span className="hud-label">Mic Status</span>
        <div className="flex items-center gap-2">
          {isMuted ? (
            <MicOff className="w-4 h-4 text-hud-danger" />
          ) : (
            <Mic className="w-4 h-4 text-hud-success" />
          )}
          <span className="font-mono text-xs text-hud-text">
            {isMuted ? "Disconnected" : "Active"}
          </span>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span className="hud-label">TTS Status</span>
        <span className="font-mono text-xs text-hud-text-dim">Idle</span>
      </div>

      <div className="flex flex-col gap-2">
        <span className="hud-label">Wake Phrase</span>
        <span className="font-mono text-xs text-hud-text">"onyx"</span>
      </div>

      <div className="flex flex-col gap-2">
        <span className="hud-label">Noise Filter</span>
        <span className="font-mono text-xs text-hud-text">VAD + Whisper</span>
      </div>
    </div>
  );
}