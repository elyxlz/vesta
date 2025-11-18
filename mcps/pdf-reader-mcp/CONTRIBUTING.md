# Contributing to PDF Reader MCP Server

Thank you for considering contributing! We welcome contributions from the community.

## How to Contribute

1.  **Reporting Issues:** If you find a bug or have a feature request, please open an issue on GitHub.

    - Provide a clear description of the issue.
    - Include steps to reproduce (for bugs).
    - Explain the motivation for the feature request.

2.  **Submitting Pull Requests:**
    - Fork the repository.
    - Create a new branch for your feature or bugfix (e.g., `feature/new-pdf-feature` or `bugfix/parsing-error`).
    - Make your changes, adhering to the project's coding style and guidelines (ESLint, Prettier).
    - Add tests for your changes and ensure all tests pass (`npm test`).
    - Ensure your commit messages follow the Conventional Commits standard.
    - Push your branch to your fork.
    - Open a Pull Request against the `main` branch of the `sylphlab/pdf-reader-mcp` repository.
    - Provide a clear description of your changes in the PR.

## Development Setup

1.  Clone the repository: `git clone https://github.com/sylphlab/pdf-reader-mcp.git`
2.  Navigate into the directory: `cd pdf-reader-mcp`
3.  Install dependencies: `npm install`
4.  Build the project: `npm run build`
5.  Run tests: `npm test`
6.  Use `npm run watch` during development for automatic recompilation.
7.  Use `npm run validate` before committing to check formatting, linting, and tests.

## Code Style

- We use Prettier for code formatting and ESLint (with strict TypeScript rules) for linting.
- Please run `npm run format` and `npm run lint:fix` before committing your changes.
- Git hooks are set up using Husky and lint-staged to automatically check staged files.

## Commit Messages

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification. Commit messages are linted using `commitlint` via a Git hook.

Example:

```
feat: add support for encrypted PDFs

Implemented handling for password-protected PDF files using an optional password parameter.
```

## License

By contributing, you agree that your contributions will be licensed under the MIT License that covers the project.
