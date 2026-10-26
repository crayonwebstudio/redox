# Woodwolf Digital website (Redox template migration)

A production-ready Astro static site migrated from the supplied Redox HTML template
demo, curated to a canonical site and rebranded in content to Woodwolf Digital.

Live domain (after Coolify deployment): https://redox.woodwolfdigital.com

## Canonical pages

- `/` Home (the original digital-agency homepage)
- `/about/`, `/services/`, `/service-details/`
- `/portfolio/`, `/portfolio-details/`
- `/blog/`, `/blog-details/`
- `/team/`, `/team-details/`
- `/contact/`, `/faq/`
- `/404.html` custom 404 page (noindex, excluded from the sitemap)

Demo variant homepages, service variants (services-2 to services-6) and portfolio
effect pages from the template are intentionally not built. Their old links are
retargeted to the matching canonical page, so no link in the built site points
to a missing page.

## Content identity

- Brand used throughout the content: Woodwolf Digital
- Email: info@woodwolfdigital.com
- Phone: +91 9375767751

The template's demo street address, demo office cities (New York, Toronto,
Berlin, London) and placeholder phone number were removed, not carried over.
No social profiles are linked, because none were supplied; the footer social
names are shown as text only. No prices, testimonials, certifications or
statistics were invented.

## Architecture

- `src/layouts/BaseLayout.astro`: document, SEO head, preloader, cursor,
  off-canvas side panel, header, GSAP smooth-scroll wrappers, footer, scripts.
- `src/components/SEO.astro`: title, description, canonical, Open Graph,
  Twitter card, robots directive and JSON-LD (Organization, WebSite, WebPage,
  BreadcrumbList, FAQPage on the FAQ page only).
- `src/components/Header.astro` / `Footer.astro` / `SideInfo.astro`: shared
  chrome, loaded from `src/data/*.html` so the template markup stays intact.
- `src/pages/*.astro`: one page per canonical route, with the original
  section markup preserved and only the first section heading promoted to H1
  (same class, so visuals are unchanged).
- `public/assets/`: template CSS, vendor JS/CSS, fonts and only the images
  referenced by the canonical pages.
- `public/js/site.js`: front-end form handling (see Forms below).
- `public/robots.txt`, auto-generated `sitemap-index.xml` /
  `sitemap-0.xml` (via `@astrojs/sitemap`), `public/llms.txt`.

## Forms

There is no PHP backend in this build, so the template's `mail.php` was not
carried over (it also posted to the template author's address).

- Contact form (`/contact/`): validated in the browser, then opens the
  visitor's email app with a message addressed to info@woodwolfdigital.com.
  A status message explains exactly that; it does not claim a message was sent.
- Subscribe forms: validated in the browser and show an honest pending state,
  because no mailing backend is connected yet. Wire one up before presenting
  subscriptions as live.

## SEO, AEO, GEO and SXO

- Unique title and description per page, canonical URLs on the production
  domain, one H1 per page, Open Graph and Twitter cards, JSON-LD as above.
- Clean lowercase URLs; old `.html` URLs redirect to the clean URL in
  `nginx.conf` (permanent redirect, not to the homepage). Nginx uses
  `try_files $uri $uri/` plus the index directive; adding `$uri/index.html`
  as a try_files term was tried first and broke every page by redirecting
  `/about/` to `/about/index/`, so it must not be reintroduced.
- `robots.txt` allows public content and points at `sitemap-index.xml`.
- Images below the fold use `loading="lazy"`; the first image is not lazy.
- Forms have labels (aria-labels where the template used placeholders only),
  validation and status messages; a skip link is provided.
- `prefers-reduced-motion` disables CSS animations and transitions.
- Google Search Console and Analytics are configurable only: set
  `PUBLIC_GSC_VERIFICATION` and `PUBLIC_GA_MEASUREMENT_ID` in the environment.
  With them blank, no verification tag and no tracking script is emitted, and
  no placeholder IDs are shipped.

## Development

```sh
npm install
npm run dev
npm run build
npm run preview
```

Set `SITE_URL` to change the canonical domain for a non-production build
(default https://redox.woodwolfdigital.com). Copy `.env.example` values into
your deployment environment; never commit a real `.env` file.

## Deployment (Coolify, Docker)

The repo includes a `Dockerfile` (Node build, Nginx serve) and `nginx.conf`.
In Coolify, create an application from this repository, branch `main`,
build pack Dockerfile, domain `redox.woodwolfdigital.com`, with HTTPS enabled.
Nginx serves the static build, redirects `.html` URLs to clean URLs, and
serves the custom 404 page.

## Known gaps, not hidden

- The logo image files are the template's logo graphics; the wordmark in the
  image itself was not redrawn. Replace `public/assets/imgs/logo/` if you want
  a Woodwolf Digital logo image.
- Blog, portfolio and team entries are the template's demo entries, not real
  Woodwolf Digital projects, posts or people. Replace them with real content
  before presenting the site as a portfolio of completed work.
- No real privacy policy page exists in the supplied files, so the footer
  shows "Privacy Policy" as text, not a link to a page that does not exist.

## Homepage variants (added 2026-10-26)

The template shipped 17 homepage variants. The main homepage stays at `/`.
The other 16 live as separate pages, each keeping its own template header,
footer, side-info, stylesheet (style.css or ad-style.css) and vendor scripts:

- /digital-agency/, /marketing-agency/, /digital-web-agency/

The other 13 template homepages (creative-agency, design-agency, startup-agency,
modern-agency, agency-portfolio, branding-agency, modern-agency-2,
agency-portfolio-2, agency-portfolio-3, web-design, web-development,
it-solution, modern-agency-3) were removed 2026-10-26 at milan's request and
now return the custom 404 page. Links to them from the remaining variants
point to the main homepage.

Variant pages use `src/layouts/VariantLayout.astro` with per-variant header,
footer and side-info fragments in `src/data/variants/`. They carry the same
Woodwolf Digital branding and link retargeting as the canonical pages, but
they are `noindex, nofollow` and excluded from the sitemap in
`astro.config.mjs`, so they are viewable without creating duplicate-content
competition for the main homepage. They are not in the main navigation;
the template's own Home dropdown inside variant headers links between them.
Placeholder links inside variants (404 demo page, Privacy Policy, social
names) are plain text spans, not invented pages or profiles, and demo
addresses were removed outright, matching the canonical pages.
