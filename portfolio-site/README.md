# Portfolio site

A static portfolio for Lakshya Kumar ([kumarlakshya24](https://github.com/kumarlakshya24)), written for Applied AI Architect, AI Engineer, and Solutions Architect reviews.

The page covers the six systems on `main` — Aegis, Switchboard, Lumen, Forge, Atlas, and Lens — plus a Wave 2 strip for Conduit, Arena, Charter, and Skyline. Project copy, diagrams, decisions, and numbers live in [`src/data/projects.ts`](src/data/projects.ts). Fill that file in when a Wave 2 branch lands. Do not add a number that is not already in the project’s README or committed report.

## Why Astro

Astro’s default output is a static site: HTML, CSS, and two short scripts (theme before paint, theme toggle after). There is no client framework and no server. Next.js can static-export too, but it still carries the React runtime for a page that does not need it. Astro keeps the shipped page small, which is the point of a portfolio someone opens on a phone between meetings.

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

Light and dark follow the operating system until the visitor chooses. The choice is stored in `localStorage`. The header button is named “Dark mode” or “Light mode” for the action it will take. Body text and links are sized and colored for WCAG AA contrast. Diagrams are real text, not a bitmap. `prefers-reduced-motion` turns off smooth scrolling.

## What a later Vercel preview needs

This repository change does not deploy anything.

When you want a preview:

1. Import `kumarlakshya24/personal-projects` in Vercel.
2. Set the root directory to `portfolio-site`.
3. Framework preset: Astro. Build command: `npm run build`. Output directory: `dist`.
4. No environment variables.
5. Leave production deploys off until you want a public URL. A preview deployment on the pull request is enough to click through.

There is no `vercel.json`. The static export does not need one.
