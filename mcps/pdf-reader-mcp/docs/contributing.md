# Contributing to PDF Reader MCP Server

Thank you for your interest in contributing!

## How to Contribute

We welcome contributions in various forms:

- **Reporting Bugs:** If you find a bug, please open an issue on GitHub detailing the problem, steps to reproduce, and your environment.
- **Suggesting Enhancements:** Have an idea for a new feature or improvement? Open an issue to discuss it.
- **Pull Requests:** If you'd like to contribute code:
  1.  Fork the repository.
  2.  Create a new branch for your feature or bug fix (`git checkout -b feature/your-feature-name` or `bugfix/issue-number`).
  3.  Make your changes, ensuring they adhere to the project's coding style and principles (see `docs/principles.md`).
  4.  Add tests for any new functionality and ensure all tests pass (`npm test`).
  5.  Ensure code coverage remains high (`npm run test:cov`).
  6.  Make sure your code lints correctly (`npm run lint`).
  7.  Commit your changes using the [Conventional Commits](https://www.conventionalcommits.org/) standard (e.g., `feat: Add support for encrypted PDFs`, `fix: Correct page range parsing`).
  8.  Push your branch to your fork (`git push origin feature/your-feature-name`).
  9.  Open a Pull Request against the `main` branch of the original repository.

## Development Setup

1.  Clone your fork.
2.  Install dependencies: `npm install`
3.  Build the project: `npm run build`
4.  Run in watch mode during development: `npm run watch`
5.  Run tests: `npm test` or `npm run test:watch`

## Code Style

Please ensure your code adheres to the formatting and linting rules defined in the project:

- Run `npm run format` to format your code with Prettier.
- Run `npm run lint` to check for ESLint issues.

Thank you for contributing!
