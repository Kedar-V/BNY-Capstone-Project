/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        navy: {
          50: '#f1f5fa', 100: '#dce6f3', 200: '#b9cce6', 300: '#8aa9d1', 400: '#5f86bb',
          500: '#3a63a0', 600: '#244b82', 700: '#1b3a66', 800: '#12294a', 900: '#0b1f3a', 950: '#071429',
        },
      },
      fontFamily: { sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'] },
    },
  },
  plugins: [],
}
