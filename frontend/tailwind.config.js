/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // RuralCare (individual layer) — calm clinical teal
        care: {
          50: '#eefbf7',
          100: '#d3f4ea',
          200: '#a8e8d6',
          500: '#0e9f77',
          600: '#0b8262',
          700: '#0a6650',
          900: '#07332a',
        },
        // GramSentinel (community layer) — deeper surveillance indigo
        sentinel: {
          50: '#eef2fb',
          100: '#dbe3f6',
          200: '#b8c7ed',
          500: '#3b5bad',
          600: '#2f4890',
          700: '#253972',
          900: '#141f3e',
        },
        ink: {
          50: '#f7f8fa',
          100: '#eef0f4',
          200: '#dde1e9',
          400: '#8a94a6',
          600: '#4d5666',
          800: '#252b36',
          900: '#151920',
        },
      },
      fontFamily: {
        sans: ['Inter', 'Segoe UI', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}
