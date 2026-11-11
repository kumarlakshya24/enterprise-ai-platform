import { defineConfig } from "astro/config";

export default defineConfig({
  // Served by GitHub Pages as a project site. Change both lines if a custom domain is added later.
  site: "https://kumarlakshya24.github.io",
  base: "/enterprise-ai-platform/",
  output: "static",
  compressHTML: true,
});
