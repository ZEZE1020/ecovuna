import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/pages/**/*.{js,ts,jsx,tsx,mdx}", "./src/components/**/*.{js,ts,jsx,tsx,mdx}", "./src/app/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        forest: "#087f5b",
        midnight: "#17324d",
      },
    },
  },
  daisyui: {
    themes: [
      {
        ecovuna: {
          primary: "#087f5b",
          secondary: "#28638f",
          accent: "#e2a03a",
          neutral: "#17324d",
          "base-100": "#ffffff",
          "base-200": "#f4f7f9",
          "base-300": "#dbe3e9",
          "base-content": "#243647",
          info: "#28638f",
          success: "#087f5b",
          warning: "#a15c00",
          error: "#b53c3c",
        },
      },
    ],
  },
  plugins: [require("daisyui")],
};

export default config;
