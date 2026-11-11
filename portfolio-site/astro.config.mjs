import { defineConfig } from "astro/config";

export default defineConfig({
  // The planned domain. Used for absolute share-image URLs; nothing is deployed.
  site: "https://lakshyak.com",
  output: "static",
  compressHTML: true,
});
