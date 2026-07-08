import { useCanvasStore } from '@/store/canvasStore'
import { WidgetRenderer } from '@/components/CanvasWidgets'

/**
 * Phase 3 — assistant-populated canvas.
 *
 * State comes exclusively from `canvasStore`, which is fed by the WS
 * `canvas_update` event dispatched from socket.ts. The assistant emits
 * a validated widget layout via the `render_canvas` tool, the strict
 * pydantic schema runs server-side, then the event lands here.
 *
 * There is NO other write path into the canvas. The user does not
 * drag/drop widgets in this phase; layout is 100% assistant-populated.
 */
export function Canvas() {
  const widgets = useCanvasStore((s) => s.widgets)
  const lastUpdate = useCanvasStore((s) => s.lastUpdate)

  return (
    <div className="h-full flex flex-col p-4 overflow-hidden">
      <div className="flex items-baseline gap-3 mb-4 shrink-0">
        <h1 className="font-sans font-bold text-2xl tracking-[2px] text-sgc-primary m-0">Canvas</h1>
        <span className="font-mono text-[11px] text-sgc-dim tracking-wider">
          Assistant-populated data widgets
        </span>
        {lastUpdate ? (
          <span className="ml-auto font-mono text-[10px] text-sgc-dim">
            updated {new Date(lastUpdate).toLocaleTimeString()}
          </span>
        ) : null}
      </div>

      {widgets.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-sgc-dim font-mono text-sm">
          <div className="text-center max-w-md">
            <div className="mb-2">Nothing on the canvas yet.</div>
            <div className="text-[11px] text-sgc-secondary leading-relaxed">
              Ask the assistant to populate it — e.g. "show me the weather in Bengaluru
              and the top tech news."
            </div>
          </div>
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto">
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {widgets.map((w) => (
              <WidgetRenderer key={w.id} widget={w} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
