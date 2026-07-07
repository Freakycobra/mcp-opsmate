/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Warm, low-saturation color palette
        opsmate: {
          50:  '#faf8f5',
          100: '#f3efe9',
          200: '#e8e0d4',
          300: '#d4c8b8',
          400: '#b8a898',
          500: '#9c8878',
          600: '#7d6c5e',
          700: '#5e5046',
          800: '#3d342e',
          900: '#1e1a17',
        },
        // Status colors - muted
        status: {
          pending:    { bg: '#f3efe9', text: '#7d6c5e', border: '#d4c8b8' },
          running:    { bg: '#e8f0fe', text: '#4a7ec7', border: '#a8c4f0' },
          completed:  { bg: '#e8f5e9', text: '#4a8c5c', border: '#a8d8b8' },
          failed:     { bg: '#fce8e6', text: '#c75a4a', border: '#f0a8a0' },
          cancelled:  { bg: '#f5f5f5', text: '#888888', border: '#cccccc' },
          paused:     { bg: '#fff8e1', text: '#b08d2b', border: '#e8d8a0' },
        },
        // Mode colors
        mode: {
          mock:  { bg: '#fff8e1', text: '#b08d2b', border: '#e8d8a0' },
          live:  { bg: '#e8f5e9', text: '#4a8c5c', border: '#a8d8b8' },
          mixed: { bg: '#e8f0fe', text: '#4a7ec7', border: '#a8c4f0' },
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          'system-ui',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'Roboto',
          'sans-serif',
        ],
        mono: [
          'JetBrains Mono',
          'Fira Code',
          'Consolas',
          'Monaco',
          'monospace',
        ],
      },
      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '0.875rem' }],
      },
      spacing: {
        '18': '4.5rem',
        '88': '22rem',
      },
      borderRadius: {
        'xl': '0.75rem',
        '2xl': '1rem',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-in': 'fadeIn 0.2s ease-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'pulse-live': 'pulseLive 2s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        pulseLive: {
          '0%, 100%': { opacity: '1', boxShadow: '0 0 0 0 rgba(74, 140, 92, 0.4)' },
          '50%': { opacity: '0.85', boxShadow: '0 0 0 8px rgba(74, 140, 92, 0)' },
        },
      },
      boxShadow: {
        'soft': '0 1px 3px rgba(30, 26, 23, 0.04), 0 1px 2px rgba(30, 26, 23, 0.06)',
        'card': '0 2px 8px rgba(30, 26, 23, 0.06), 0 1px 3px rgba(30, 26, 23, 0.04)',
        'elevated': '0 8px 24px rgba(30, 26, 23, 0.08), 0 2px 8px rgba(30, 26, 23, 0.04)',
      },
    },
  },
  plugins: [],
};
