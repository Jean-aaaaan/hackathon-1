import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // CSS variable-based theming
        border: "hsl(var(--border))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        ring: "hsl(var(--ring))",
        // Vantage brand — indigo-500 as accent, violet as gradient second stop
        lily: {
          DEFAULT: "#FFFEFC",
          wash:    "#FAFAF8",
        },
        brand: {
          50:  "#EEF2FF",   // indigo-50
          100: "#E0E7FF",   // indigo-100
          200: "#C7D2FE",   // indigo-200
          300: "#A5B4FC",   // indigo-300
          400: "#818CF8",   // indigo-400
          500: "#6366F1",   // indigo-500
          600: "#4F46E5",   // indigo-600
          700: "#4338CA",   // indigo-700
          900: "#312E81",   // indigo-900
        },
        violet: {
          50:  "#F5F3FF",
          100: "#EDE9FE",
          400: "#A78BFA",
          500: "#8B5CF6",
          600: "#7C3AED",
        },
        // Urgency levels (semantic — data, not brand)
        urgency: {
          critical: "#EF4444",
          high:     "#F97316",
          medium:   "#F59E0B",
          low:      "#10B981",
        },
        // Forecast categories
        forecast: {
          commit:    "#10B981",   // emerald
          bestcase:  "#0EA5E9",   // sky
          pipeline:  "#8B5CF6",   // violet
          omit:      "#71717A",   // zinc-500
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Menlo", "monospace"],
      },
      animation: {
        "urgency-critical": "urgency-pulse 2s ease-in-out infinite",
        "urgency-high":     "urgency-pulse-high 3s ease-in-out infinite",
        "thinking":         "thinking-dot 1.4s infinite ease-in-out",
        "palette-in":       "palette-in 0.15s ease-out",
        "nav-slide-in":     "nav-slide-in 0.2s ease-out",
        "ring-fill":        "ring-fill 1.2s ease-out forwards",
        "fade-up":          "fade-up 0.3s ease-out",
      },
      keyframes: {
        "urgency-pulse": {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(239,68,68,0.5)" },
          "50%":       { boxShadow: "0 0 0 5px rgba(239,68,68,0)" },
        },
        "urgency-pulse-high": {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(249,115,22,0.4)" },
          "50%":       { boxShadow: "0 0 0 4px rgba(249,115,22,0)" },
        },
        "thinking-dot": {
          "0%, 80%, 100%": { opacity: "0.2", transform: "scale(0.75)" },
          "40%":           { opacity: "1",   transform: "scale(1)" },
        },
        "palette-in": {
          from: { opacity: "0", transform: "scale(0.97) translateY(-8px)" },
          to:   { opacity: "1", transform: "scale(1) translateY(0)" },
        },
        "nav-slide-in": {
          from: { transform: "scaleY(0)" },
          to:   { transform: "scaleY(1)" },
        },
        "ring-fill": {
          from: { strokeDashoffset: "251.2" },
          to:   { strokeDashoffset: "var(--ring-offset, 0)" },
        },
        "fade-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [
    require("@tailwindcss/forms"),
    require("@tailwindcss/typography"),
  ],
};

export default config;
