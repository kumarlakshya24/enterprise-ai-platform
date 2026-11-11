# Portfolio site

A static portfolio for Lakshya Kumar ([kumarlakshya24](https://github.com/kumarlakshya24)), written for Applied AI Architect, AI Engineer, and Solutions Architect reviews.

The home page shows all ten systems on `main` as cards: Aegis, Switchboard, Lumen, Forge, Atlas, Lens, Charter, Arena, Conduit, and Skyline. Each card opens a page with that project's problem, architecture, decisions, and measured results. Project copy, diagrams, decisions, and numbers live in [`src/data/projects.ts`](src/data/projects.ts). Do not add a number that is not already in the project's README or committed report.

## Customising the look

- **Theme:** dark by default. The header button switches to light, and the choice is stored in `localStorage`.
- **Accent colour:** five swatches in the header (violet, blue, emerald, amber, rose). To add one, add a `[data-accent]` rule in [`src/styles/global.css`](src/styles/global.css) and a swatch in [`src/components/SiteHeader.astro`](src/components/SiteHeader.astro).
- **Project colours:** `projectColor` in `src/data/projects.ts`, the same colour per project that the repository diagrams use.
- **Card screenshots:** one WebP per project in `public/shots/`, resized from each project's `docs/assets`. They are copies, so the site does not depend on the repository being public.

## Why Astro

Astro’s default output is a static site: HTML, CSS, and two short scripts (theme and accent before paint, the two controls after). There is no client framework and no server. Next.js can static-export too, but it still carries the React runtime for a page that does not need it. Astro keeps the shipped page small, which is the point of a portfolio someone opens on a phone between meetings.

Diagrams are HTML drawings of the Mermaid in each `ARCHITECTURE.md`, not a Mermaid runtime. The type stays at a normal size on a phone, and the figure caption points back at the source document.

## Run

Requirements: Node.js 22 or newer.

```bash
cd portfolio-site
npm install
npm run dev
```

Open http://127.0.0.1:4321.

## Build

```bash
npm run build
npm run preview
```

`npm run build` writes a static site to `dist/`. `npm run check` runs the Astro type check.

The build does not call a network API and does not need environment variables.

## Themes and access

The page is dark until the visitor chooses light. Body text and links are sized and coloured for WCAG AA contrast in both themes. Diagrams are real text, not a bitmap. `prefers-reduced-motion` turns off smooth scrolling and hover transitions.

## Hosting on GitHub Pages

`.github/workflows/portfolio-site-pages.yml` builds this folder and publishes it to GitHub Pages on every push to `main` that touches `portfolio-site/`. It can also be run by hand from the Actions tab. `public/CNAME` holds the custom domain, `lakshyak.com`, and `astro.config.mjs` sets the same `site` so share images use absolute URLs.

Before the first run, the repository owner sets **Settings > Pages > Source** to **GitHub Actions** and enters `lakshyak.com` as the custom domain. DNS for the domain points at GitHub Pages as described in GitHub's custom domain guide.

