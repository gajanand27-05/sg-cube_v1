/** Runtime theme switching. Themes are pure CSS — see the `[data-theme]`
 *  blocks in index.css. This module just picks which one is active and
 *  persists it. Adding a theme = one CSS block + one entry in THEMES. */

export type ThemeName = "cyan" | "amber"

export const THEMES: { id: ThemeName; label: string; swatch: string }[] = [
  { id: "cyan", label: "Cyan HUD", swatch: "#00f3ff" },
  { id: "amber", label: "Amber Command", swatch: "#ffb700" },
]

const KEY = "sgc-theme"

function isTheme(v: string | null): v is ThemeName {
  return v === "cyan" || v === "amber"
}

export function getStoredTheme(): ThemeName {
  const v = localStorage.getItem(KEY)
  return isTheme(v) ? v : "cyan"
}

export function applyTheme(theme: ThemeName): void {
  document.documentElement.dataset.theme = theme
  localStorage.setItem(KEY, theme)
}
