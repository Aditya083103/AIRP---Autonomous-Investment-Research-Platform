// frontend/postcss.config.js
// PostCSS pipeline for Tailwind. ESM syntax because package.json sets
// "type": "module". Not type-checked or linted (lives outside src/).
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
