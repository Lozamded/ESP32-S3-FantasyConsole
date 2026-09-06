// @ts-check
const { themes } = require('prism-react-renderer');

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'TurtleReader Docs',
  tagline: 'Fantasy console for ESP32-S3 — Lua cartridges, pixel art, and indie games',
  favicon: 'img/favicon.ico',

  url: 'https://your-site.example.com',
  baseUrl: '/',

  onBrokenLinks: 'throw',
  onBrokenMarkdownLinks: 'warn',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          sidebarPath: require.resolve('./sidebars.js'),
          routeBasePath: '/',
        },
        blog: false,
        theme: {
          customCss: require.resolve('./src/css/custom.css'),
        },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      colorMode: {
        defaultMode: 'dark',
        disableSwitch: false,
        respectPrefersColorScheme: false,
      },
      navbar: {
        title: 'TurtleReader',
        logo: {
          alt: 'TurtleReader Logo',
          src: 'img/logo.svg',
        },
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'mainSidebar',
            position: 'left',
            label: 'Docs',
          },
          {
            href: 'https://github.com/your-repo/FantasyConsole',
            label: 'GitHub',
            position: 'right',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'Docs',
            items: [
              { label: 'Getting Started', to: '/intro' },
              { label: 'Cartridge Format', to: '/cartridge/turtlecart-format' },
              { label: 'Lua API', to: '/lua/overview' },
            ],
          },
          {
            title: 'Reference',
            items: [
              { label: 'Asset Formats', to: '/assets/binary-formats' },
              { label: 'TurtleStudio', to: '/turtlestudio/guide' },
            ],
          },
        ],
        copyright: `TurtleReader Fantasy Console — ESP32-S3 + Lua 5.4`,
      },
      prism: {
        theme: themes.vsDark,
        darkTheme: themes.vsDark,
        additionalLanguages: ['lua', 'json', 'bash'],
      },
    }),
};

module.exports = config;
