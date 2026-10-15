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
        brand: {
          50: '#ecf8fa', 100: '#d1f0f5', 200: '#a5e0ea', 300: '#6fc8d8', 400: '#43b0c3',
          500: '#2b9cae', 600: '#217f8f', 700: '#1d6673', 800: '#1c515c', 900: '#1b434c',
        },
      },
      fontFamily: { sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'] },
    },
  },
  plugins: [],
}
