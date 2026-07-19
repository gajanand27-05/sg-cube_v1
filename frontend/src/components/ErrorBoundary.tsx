import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** Catches render errors so one bad panel can't blank the whole HUD.
 *
 *  Must be a class — React exposes no hook equivalent of componentDidCatch.
 *  Wrapped around <main> rather than the whole app so the Header and BottomBar
 *  survive a panel crash and the shell still reads as alive.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[HUD] panel crashed:", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <main className="flex-1 grid place-items-center p-3">
        <section className="hud-panel max-w-lg w-full p-6">
          <div className="text-[10px] uppercase tracking-[0.2em] font-semibold text-hud-danger">
            Panel Error
          </div>
          <div className="mt-3 font-mono text-[11px] text-hud-text-dim break-words">
            {error.message || String(error)}
          </div>
        </section>
      </main>
    );
  }
}
