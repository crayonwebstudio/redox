import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

const site = process.env.SITE_URL || 'https://redox.woodwolfdigital.com';

export default defineConfig({
  site,
  trailingSlash: 'always',
  integrations: [
    sitemap({
      // The 404 page is excluded, and /digital-agency/ is excluded because
      // it duplicates the homepage content (it is noindex, canonical /).
      filter: (page) =>
        !page.endsWith('/404/') &&
        !page.endsWith('/404.html') &&
        !page.endsWith('/digital-agency/'),
    }),
  ],
});
