module.exports = {
  content: {
    relative: true,
    files: [
      "./templates/**/*.html",
      "./static/**/*.js",
      "!./static/vendor/**",
      "./src/**/*.{js,css}"
    ]
  },
  theme: {
    extend: {}
  },
  plugins: []
};
