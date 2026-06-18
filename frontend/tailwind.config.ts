import type { Config } from 'tailwindcss';

// Design tokens inspired by a modern immigration-law aesthetic: deep navy primary,
// teal accent, warm off-white canvas, clean sans, generous whitespace, rounded surfaces.
// (Visual language only — no brand assets, copy, or marks.)
const config: Config = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        // `brand` (and a remap of `blue`) → deep navy primary
        brand: {
          50: '#eef3f8',
          100: '#d6e2ee',
          200: '#aec6dd',
          300: '#7fa3c6',
          400: '#4d7aa8',
          500: '#2b5887',
          600: '#163a63',
          700: '#102c4c',
          800: '#0b1f37',
          900: '#071425',
        },
        blue: {
          50: '#eef3f8',
          100: '#d6e2ee',
          200: '#aec6dd',
          300: '#7fa3c6',
          400: '#4d7aa8',
          500: '#2b5887',
          600: '#163a63',
          700: '#102c4c',
          800: '#0b1f37',
          900: '#071425',
        },
        accent: {
          50: '#e7faf7',
          100: '#c6f2ec',
          400: '#2dd4bf',
          500: '#14b8a6',
          600: '#0d9488',
          700: '#0f766e',
        },
        canvas: '#f7f6f2', // warm off-white background
      },
      fontFamily: {
        sans: [
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
      },
      borderRadius: {
        xl: '0.9rem',
        '2xl': '1.25rem',
      },
    },
  },
  plugins: [],
};

export default config;
