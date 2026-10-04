/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        terminal: {
          bg: '#0b0e11',
          surface: '#151a1e',
          card: '#1e2329',
          border: '#2b313a',
          hover: '#262d35',
          text: '#eaecef',
          muted: '#848e9c',
        },
        trade: {
          buy: '#0ecb81',
          buySoft: 'rgba(14, 203, 129, 0.12)',
          sell: '#f6465d',
          sellSoft: 'rgba(246, 70, 93, 0.12)',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Roboto Mono', 'SFMono-Regular', 'Consolas', 'monospace'],
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
