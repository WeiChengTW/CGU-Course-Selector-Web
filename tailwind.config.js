/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/templates/**/*.html',
  ],
  theme: {
    extend: {
      colors: {
        'cgu-orange': '#E39800',
        'cgu-orange-dark': '#C48400',
        'cgu-orange-light': '#F5B333',
        'cgu-slate': '#333333',
        'cgu-sand': '#D1C7AC',
        'cgu-sand-light': '#E8E2D6',
        'cgu-pearl': '#F9F9F9',
      },
    },
  },
  plugins: [],
}