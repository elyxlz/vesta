// docs/.vitepress/config.mts
import { defineConfig } from 'vitepress';

export default defineConfig({
  lang: 'en-US',
  title: 'PDF Reader MCP Server',
  description: 'MCP Server for reading PDF files securely within a project.',
  lastUpdated: true,

  themeConfig: {
    logo: '/logo.svg', // Assuming logo is in docs/public
    nav: [
      { text: 'Home', link: '/' },
      { text: 'Guide', link: '/guide/' },
      { text: 'API Reference', link: '/api/' },
      { text: 'Design', link: '/design/' },
      { text: 'Performance', link: '/performance/' },
      { text: 'Comparison', link: '/comparison/' },
    ],

    sidebar: {
      '/guide/': [
        {
          text: 'Introduction',
          items: [
            { text: 'What is PDF Reader MCP?', link: '/guide/' },
            { text: 'Installation', link: '/guide/installation' },
            { text: 'Getting Started', link: '/guide/getting-started' },
          ],
        },
        // Add more guide sections later
      ],
      '/api/': [
        {
          text: 'API Reference',
          items: [{ text: 'Tool: read_pdf', link: '/api/read_pdf' }],
        },
      ],
      // Add sidebars for other sections
      '/design/': [
        {
          text: 'Design',
          items: [{ text: 'Philosophy', link: '/design/' }],
        },
      ],
      '/performance/': [
        {
          text: 'Performance',
          items: [{ text: 'Benchmarks', link: '/performance/' }],
        },
      ],
      '/comparison/': [
        {
          text: 'Comparison',
          items: [{ text: 'Other Solutions', link: '/comparison/' }],
        },
      ],
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/sylphlab/pdf-reader-mcp' },
      { icon: 'issues', link: 'https://github.com/sylphlab/pdf-reader-mcp/issues' }, // Add link to issues
    ],

    footer: {
      message: 'Released under the MIT License. Found this useful? Give us a star ⭐ on GitHub!', // Add call-to-action
      copyright: `Copyright © ${new Date().getFullYear()} Sylph Lab`,
    },

    // Enable edit links
    editLink: {
      pattern: 'https://github.com/sylphlab/pdf-reader-mcp/edit/main/docs/:path',
      text: 'Edit this page on GitHub',
    },
  },

  // Enable markdown features
  markdown: {
    lineNumbers: true,
  },
});
