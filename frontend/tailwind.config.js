/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        sgc: {
          bg: "var(--c-bg)",
          panel: "var(--c-panel)",
          hover: "#040c14",
          active: "#06121e",
          border: "rgb(var(--c-border) / <alpha-value>)",
          "border-bright": "rgb(var(--c-border-bright) / <alpha-value>)",
          primary: "rgb(var(--c-primary) / <alpha-value>)",
          secondary: "rgb(var(--c-secondary) / <alpha-value>)",
          dim: "rgb(var(--c-dim) / <alpha-value>)",
          bright: "rgb(var(--c-bright) / <alpha-value>)",
          danger: "rgb(var(--c-danger) / <alpha-value>)",
          warn: "rgb(var(--c-warn) / <alpha-value>)",
          accent: "rgb(var(--c-accent) / <alpha-value>)",
          "accent-bright": "rgb(var(--c-accent-bright) / <alpha-value>)",
          ai: "rgb(var(--c-ai) / <alpha-value>)",
          memory: "rgb(var(--c-memory) / <alpha-value>)",
          vision: "rgb(var(--c-vision) / <alpha-value>)",
          reason: "rgb(var(--c-reason) / <alpha-value>)",
          tools: "rgb(var(--c-tools) / <alpha-value>)",
        },
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "Consolas", "monospace"],
        sans: ["Rajdhani", "Inter", "-apple-system", "BlinkMacSystemFont", "sans-serif"],
      },
      keyframes: {
        blink: { "0%, 100%": { opacity: "1" }, "50%": { opacity: "0" } },
        pulse: {
          "0%, 100%": { boxShadow: "0 0 20px rgba(255,0,60,0.2)" },
          "50%": { boxShadow: "0 0 40px rgba(255,0,60,0.5)" },
        },
        "spin-slow": { "100%": { transform: "rotate(360deg)" } },
        "cube-rotate": {
          from: { transform: "rotateX(-20deg) rotateY(0)" },
          to: { transform: "rotateX(-20deg) rotateY(-360deg)" },
        },
      },
      animation: {
        blink: "blink 1.2s infinite",
        pulse: "pulse 1.5s infinite",
        "spin-slow": "spin-slow 5s linear infinite",
        "cube-rotate": "cube-rotate 8s linear infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
}
