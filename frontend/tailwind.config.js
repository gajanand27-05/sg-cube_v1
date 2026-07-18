/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: {
          base: "#040814",
          panel: "#060b1a",
          raised: "#0a1226",
        },
        hud: {
          cyan: "#22d3ee",
          "cyan-dim": "#0891b2",
          "cyan-glow": "#67e8f9",
          border: "rgba(34, 211, 238, 0.35)",
          "border-strong": "rgba(34, 211, 238, 0.6)",
          "border-dim": "rgba(34, 211, 238, 0.15)",
          text: "#e0f2fe",
          "text-dim": "#7ea3b8",
          "text-muted": "#4b6478",
          success: "#22c55e",
          warning: "#f59e0b",
          danger: "#ef4444",
        },
      },
      fontFamily: {
        display: ["Orbitron", "sans-serif"],
        hud: ["Rajdhani", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      boxShadow: {
        "hud-glow": "0 0 20px rgba(34, 211, 238, 0.15)",
        "hud-glow-strong": "0 0 30px rgba(34, 211, 238, 0.35)",
      },
      keyframes: {
        pulse_glow: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.5" },
        },
        scan: {
          "0%": { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100%)" },
        },
        spin_cw: {
          from: { transform: "rotate(0deg)" },
          to: { transform: "rotate(360deg)" },
        },
        spin_ccw: {
          from: { transform: "rotate(0deg)" },
          to: { transform: "rotate(-360deg)" },
        },
      },
      animation: {
        "pulse-glow": "pulse_glow 2s ease-in-out infinite",
        scan: "scan 3s linear infinite",
        "spin-slow": "spin_cw 45s linear infinite",
        "spin-slow-reverse": "spin_ccw 55s linear infinite",
        "spin-medium": "spin_cw 30s linear infinite",
        "spin-medium-reverse": "spin_ccw 22s linear infinite",
        "spin-fast-reverse": "spin_ccw 14s linear infinite",
      },
    },
  },
  plugins: [],
};
