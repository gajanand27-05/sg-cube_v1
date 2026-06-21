/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        sgc: {
          bg: "#000000",
          panel: "rgba(0,5,10,0.85)",
          hover: "#040c14",
          active: "#06121e",
          primary: "#00f3ff",
          secondary: "#00aaff",
          dim: "#005577",
          bright: "#ffffff",
          border: "#005577",
          "border-bright": "#00f3ff",
          danger: "#ff003c",
          warn: "#ffb700",
          accent: "#007799",
          "accent-bright": "#00aaff",
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
