import { useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/cn";
import { statusPillClass, statusToneClasses } from "@/components/Panel";
import type { MemoryHit } from "@/lib/uiEvents";
import {
  useUiConnectionState,
  useUiEvent,
  useUiEventListener,
} from "@/hooks/useUiEvents";

type StatusTone = "success" | "warning" | "danger" | "cyan" | "muted";
type EngineStatus = { status: string; tone: StatusTone };

const RECALLING_MS = 5_000;
// Longer than RECALLING_MS: a dropped write is not a transient blip, and the
// point is that you notice it rather than catch it in a 5s window.
const WRITE_FAIL_MS = 30_000;
const TOP_HITS = 3;

export function useMemoryEngineStatus(): EngineStatus {
  const connection = useUiConnectionState();
  const [lastHitAt, setLastHitAt] = useState<number | null>(null);
  const [lastEmpty, setLastEmpty] = useState(false);
  const [lastWriteFailAt, setLastWriteFailAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  useUiEventListener("memory_hit", (p) => {
    setLastHitAt(Date.now());
    setLastEmpty(p.results_count === 0);
  });

  useUiEventListener("memory_write_failed", () => {
    setLastWriteFailAt(Date.now());
  });

  return useMemo<EngineStatus>(() => {
    if (connection !== "open") return { status: "Offline", tone: "danger" };
    // A refused write outranks recall state: reads can look perfectly healthy
    // while every new memory is being dropped on the floor.
    if (lastWriteFailAt !== null && now - lastWriteFailAt < WRITE_FAIL_MS) {
      return { status: "Write Failed", tone: "danger" };
    }
    if (lastHitAt === null) return { status: "Standby", tone: "cyan" };
    if (now - lastHitAt < RECALLING_MS) {
      return lastEmpty
        ? { status: "No Recall", tone: "warning" }
        : { status: "Recalling", tone: "success" };
    }
    return { status: "Idle", tone: "cyan" };
  }, [connection, lastHitAt, lastEmpty, lastWriteFailAt, now]);
}

/** Header pill for the Memory Engine panel.
 *
 *  Owns its own 1s ticker, same reason AICoreStatusPill does: lifted to App it
 *  would re-render the PCB backdrop and the r3f Canvas once a second. */
export function MemoryEngineStatusPill() {
  const { status, tone } = useMemoryEngineStatus();
  return (
    <span className={cn(statusPillClass, statusToneClasses[tone])}>{status}</span>
  );
}

export function MemoryEnginePanel() {
  const last = useUiEvent("memory_hit");
  const lastWriteFail = useUiEvent("memory_write_failed");

  // Recall rate over the session: searches that returned at least one hit.
  const [searches, setSearches] = useState(0);
  const [recalled, setRecalled] = useState(0);
  useUiEventListener("memory_hit", (p) => {
    setSearches((n) => n + 1);
    if (p.results_count > 0) setRecalled((n) => n + 1);
  });

  // Refused writes. Counted for the session rather than shown transiently:
  // the damage is cumulative, and one dropped memory is worth seeing.
  const [writeFailures, setWriteFailures] = useState(0);
  useUiEventListener("memory_write_failed", () => {
    setWriteFailures((n) => n + 1);
  });

  // hits is nullable by contract — a publisher may send counts with no bodies.
  const hits: MemoryHit[] = Array.isArray(last?.hits) ? last.hits : [];
  const topHits = hits.slice(0, TOP_HITS);
  const topScore = hits.length > 0 ? hits[0].score : null;

  const entries =
    last === null || last.total_entries === null || last.total_entries === undefined
      ? null
      : last.total_entries.toLocaleString();
  const recallPct = searches === 0 ? null : `${Math.round((recalled / searches) * 100)}%`;

  return (
    <div className="flex flex-col gap-4">
      {/* Row 1 — Vector store identity + size */}
      <div className="flex items-center justify-between gap-3">
        <span className="hud-label">Vector DB</span>
        <div className="flex items-center gap-2 min-w-0 justify-end">
          <span className="font-mono text-xs text-hud-text truncate">
            {last === null || !last.collection ? "—" : last.collection}
          </span>
          <span className="font-mono text-xs text-hud-text-dim shrink-0">
            {entries === null ? "" : `· ${entries}`}
          </span>
        </div>
      </div>

      {/* Row 2 — Three-stat row */}
      <div className="grid grid-cols-3 gap-3">
        <MetricStat label="Searches" value={searches === 0 ? null : String(searches)} />
        <MetricStat label="Recall" value={recallPct} tone="cyan" />
        <MetricStat
          label="Top Score"
          value={topScore === null ? null : `${Math.round(topScore * 100)}%`}
        />
      </div>

      {/* Row 3 — What the last retrieval asked for */}
      <div className="flex items-center gap-3 min-w-0">
        <span className="hud-label shrink-0">Query</span>
        <span
          className="font-mono text-[10px] text-hud-text-dim truncate"
          title={last?.query ?? ""}
        >
          {last === null || !last.query ? "—" : last.query}
        </span>
      </div>

      {/* Row 3.5 — Refused writes. Hidden entirely when there are none, so it
          reads as an alarm rather than another stat. */}
      {writeFailures > 0 && (
        <div className="flex items-center justify-between gap-3 min-w-0">
          <span className="hud-label shrink-0 text-hud-danger">Writes Lost</span>
          <div className="flex items-center gap-3 min-w-0 justify-end">
            <span className="font-mono text-xs text-hud-danger">{writeFailures}</span>
            <span
              className="font-mono text-[10px] text-hud-text-dim truncate"
              title={lastWriteFail?.reason ?? ""}
            >
              {lastWriteFail === null ? "" : lastWriteFail.collection}
            </span>
          </div>
        </div>
      )}

      {/* Row 4 — Top hits with relevance bars */}
      <div className="flex flex-col gap-2">
        {topHits.length === 0 ? (
          <div className="text-[10px] uppercase tracking-[0.15em] text-hud-text-muted font-mono">
            {last !== null && last.results_count === 0 ? "no matches" : "awaiting recall"}
          </div>
        ) : (
          topHits.map((hit, i) => <HitRow key={`${hit.title}-${i}`} hit={hit} />)
        )}
      </div>
    </div>
  );
}

function HitRow({ hit }: { hit: MemoryHit }) {
  const pct = Math.max(0, Math.min(100, hit.score * 100));
  return (
    <div className="flex items-center gap-3 min-w-0">
      <span
        className="font-mono text-[10px] text-hud-text truncate flex-1"
        title={hit.title}
      >
        {hit.title || "(empty)"}
      </span>
      <span className="text-[9px] uppercase tracking-[0.15em] text-hud-text-muted shrink-0">
        {hit.source}
      </span>
      <div className="w-12 h-1 bg-hud-border-dim rounded-sm overflow-hidden shrink-0">
        <div
          className="h-full rounded-sm bg-hud-cyan-glow transition-all duration-200 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="font-mono text-[10px] text-hud-text-dim w-8 text-right shrink-0">
        {Math.round(pct)}%
      </span>
    </div>
  );
}

function MetricStat({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string | null;
  tone?: "default" | "cyan";
}) {
  return (
    <div className="leading-tight">
      <div className="text-[10px] uppercase tracking-[0.15em] text-hud-text-dim">
        {label}
      </div>
      <div
        className={cn(
          "text-sm font-mono",
          tone === "cyan" ? "text-hud-cyan-glow" : "text-hud-text",
        )}
      >
        {value === null ? (
          <span className="text-hud-text-dim">—</span>
        ) : (
          <span key={value} className="inline-block hud-crossfade">
            {value}
          </span>
        )}
      </div>
    </div>
  );
}
