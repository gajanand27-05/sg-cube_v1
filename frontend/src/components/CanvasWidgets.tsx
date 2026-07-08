/**
 * Phase 3 canvas widgets.
 *
 * SECURITY INVARIANT: every text value renders as {value} — React's
 * default JSX escaping is the whole defence. There is deliberately NO
 * `dangerouslySetInnerHTML` in this file. If you find yourself
 * reaching for it, stop — that turns the canvas into a stored-XSS
 * surface the moment a data tool ingests a malicious page.
 * (There's a grep test at tests/test_no_dangerous_inner_html.py.)
 */
import type {
  Widget,
  MetricWidget,
  ListWidget,
  MapWidget,
  ChartWidget,
  TextWidget,
} from '@/store/canvasStore'

const _card = "border border-sgc-border bg-sgc-panel p-3 flex flex-col gap-2"
const _title = "font-mono text-[11px] text-sgc-dim tracking-wider uppercase"

// Little stale-badge — makes cached / degraded data visibly different.
function StaleBadge({ stale, fetched_at }: { stale?: boolean; fetched_at?: string }) {
  if (!stale) return null
  return (
    <span
      className="font-mono text-[9px] tracking-wider uppercase text-sgc-warn border border-sgc-warn/60 px-1.5 py-0.5"
      title={fetched_at ? `fetched: ${fetched_at}` : undefined}
    >
      stale
    </span>
  )
}

function Provenance({ source, fetched_at, stale }: { source?: string; fetched_at?: string; stale?: boolean }) {
  if (!source && !fetched_at) return null
  return (
    <div className="flex items-center justify-between font-mono text-[9px] text-sgc-dim tracking-wider">
      <span>{source ?? ''}</span>
      <div className="flex items-center gap-2">
        {fetched_at ? <span>{new Date(fetched_at).toLocaleTimeString()}</span> : null}
        <StaleBadge stale={stale} fetched_at={fetched_at} />
      </div>
    </div>
  )
}

// ── Metric ──────────────────────────────────────────────────────────

function Metric({ w }: { w: MetricWidget }) {
  const positive = typeof w.delta === 'number' && w.delta > 0
  const negative = typeof w.delta === 'number' && w.delta < 0
  const deltaColor = positive ? 'text-[#00ff41]' : negative ? 'text-sgc-danger' : 'text-sgc-dim'
  return (
    <div className={_card}>
      <div className={_title}>{w.title}</div>
      <div className="flex items-baseline gap-2">
        <span className="font-sans font-bold text-3xl text-sgc-bright tracking-wider">
          {String(w.value)}
        </span>
        {w.unit ? <span className="font-mono text-xs text-sgc-dim">{w.unit}</span> : null}
      </div>
      {typeof w.delta === 'number' || typeof w.delta_pct === 'number' ? (
        <div className={`font-mono text-xs ${deltaColor}`}>
          {typeof w.delta === 'number' ? (positive ? '+' : '') + w.delta.toFixed(2) : ''}
          {typeof w.delta_pct === 'number' ? ` (${w.delta_pct.toFixed(2)}%)` : ''}
        </div>
      ) : null}
      <Provenance source={w.source} fetched_at={w.fetched_at} stale={w.stale} />
    </div>
  )
}

// ── List ────────────────────────────────────────────────────────────

function ListW({ w }: { w: ListWidget }) {
  return (
    <div className={_card}>
      <div className={_title}>{w.title}</div>
      <ul className="flex flex-col gap-1.5">
        {w.items.map((it, i) => (
          <li key={i} className="font-mono text-xs text-sgc-primary leading-snug">
            <div className="truncate">{it.text}</div>
            {it.subtitle ? (
              <div className="text-[10px] text-sgc-dim truncate">{it.subtitle}</div>
            ) : null}
          </li>
        ))}
      </ul>
      <Provenance source={w.source} fetched_at={w.fetched_at} stale={w.stale} />
    </div>
  )
}

// ── Map ─────────────────────────────────────────────────────────────

function MapW({ w }: { w: MapWidget }) {
  // src comes from a backend-allowlisted embed URL (validated in
  // canvas.py::_validate_map_embed). We further sandbox the iframe as
  // defence-in-depth — no top-level navigation, no forms.
  return (
    <div className={_card}>
      <div className={_title}>{w.title}</div>
      <div className="w-full h-64 border border-sgc-border overflow-hidden">
        <iframe
          src={w.embed_url}
          title={w.title}
          sandbox="allow-scripts allow-same-origin"
          referrerPolicy="no-referrer"
          className="w-full h-full"
        />
      </div>
      {typeof w.lat === 'number' && typeof w.lon === 'number' ? (
        <div className="font-mono text-[10px] text-sgc-dim">
          {w.lat.toFixed(4)}, {w.lon.toFixed(4)}
        </div>
      ) : null}
      <Provenance source={w.source} fetched_at={w.fetched_at} stale={w.stale} />
    </div>
  )
}

// ── Chart (minimal SVG sparkline — no external chart lib) ──────────

function Chart({ w }: { w: ChartWidget }) {
  const points = w.series ?? []
  const W = 240
  const H = 60
  let path = ''
  if (points.length >= 2) {
    const ys = points.map((p) => p.y)
    const yMin = Math.min(...ys)
    const yMax = Math.max(...ys)
    const range = yMax - yMin || 1
    const step = W / (points.length - 1)
    path = points
      .map((p, i) => {
        const x = i * step
        const y = H - ((p.y - yMin) / range) * H
        return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
      })
      .join(' ')
  }
  return (
    <div className={_card}>
      <div className={_title}>{w.title}</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-16 block">
        {path ? (
          <path d={path} fill="none" stroke="#00e5ff" strokeWidth="1.2" />
        ) : (
          <text x={W / 2} y={H / 2} textAnchor="middle" fontSize="10" fill="#005577">
            no data
          </text>
        )}
      </svg>
      {w.unit ? <div className="font-mono text-[10px] text-sgc-dim">{w.unit}</div> : null}
      <Provenance source={w.source} fetched_at={w.fetched_at} stale={w.stale} />
    </div>
  )
}

// ── Text ────────────────────────────────────────────────────────────

function TextW({ w }: { w: TextWidget }) {
  return (
    <div className={_card}>
      <div className={_title}>{w.title}</div>
      {/* {w.body} renders as plain text — React escapes any HTML. */}
      <div className="font-mono text-xs text-sgc-primary whitespace-pre-wrap leading-snug">
        {w.body}
      </div>
      <Provenance source={w.source} fetched_at={w.fetched_at} stale={w.stale} />
    </div>
  )
}

// ── Unsupported (safe placeholder) ─────────────────────────────────

function Unsupported({ raw }: { raw: unknown }) {
  const rawType = (raw && typeof raw === 'object' && 'type' in (raw as object))
    ? String((raw as { type: unknown }).type)
    : 'unknown'
  return (
    <div className={`${_card} opacity-70`}>
      <div className={_title}>unsupported widget</div>
      <div className="font-mono text-[10px] text-sgc-dim">
        type <span className="text-sgc-warn">{rawType}</span> is not renderable
      </div>
    </div>
  )
}

// ── Router ──────────────────────────────────────────────────────────

export function WidgetRenderer({ widget }: { widget: Widget }) {
  switch (widget.type) {
    case 'metric':
      return <Metric w={widget} />
    case 'list':
      return <ListW w={widget} />
    case 'map':
      return <MapW w={widget} />
    case 'chart':
      return <Chart w={widget} />
    case 'text':
      return <TextW w={widget} />
    default:
      // TS exhaustiveness — anything not caught renders the safe placeholder.
      return <Unsupported raw={widget} />
  }
}
