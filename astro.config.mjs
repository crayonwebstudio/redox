import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

const site = process.env.SITE_URL || 'https://redox.woodwolfdigital.com';

export default defineConfig({
  site,
  trailingSlash: 'always',
  integrations: [
    sitemap({
      // Variant homepages are viewable but noindex, so they stay out of the sitemap.
      filter: (page) =>
        !page.endsWith('/404/') &&
        !page.endsWith('/404.html') &&
        ![
          'digital-agency', 'marketing-agency', 'digital-web-agency',
        ].some((slug) => page.endsWith(`/${slug}/`)),
    }),
  ],
});
