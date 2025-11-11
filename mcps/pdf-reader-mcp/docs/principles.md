# Development Principles

This project adheres to the following core principles, based on the provided TypeScript Project Development Guidelines:

## 1. Impact-Driven

The primary goal is to solve the real problem of AI agents needing access to PDF content securely and efficiently. Features are added to serve this core purpose.

## 2. Simplicity & Minimalism

We aim for the most direct approach:

- A single, consolidated `read_pdf` tool instead of multiple specific tools.
- Leveraging the robust `pdfjs-dist` library for core parsing.
- Avoiding unnecessary abstractions.

## 3. Functional Programming Style (Influences)

While not strictly functional, the code emphasizes:

- Pure helper functions where possible (like path resolution checks).
- Minimizing side effects within core logic (parsing doesn't alter files).
- Using standard asynchronous patterns (`async/await`) effectively.

## 4. Minimal Dependencies

- Core functionality relies on `@modelcontextprotocol/sdk` and `pdfjs-dist`.
- Development dependencies are standard tools (TypeScript, ESLint, Prettier, Vitest).
- Dependencies like `glob`, `zod`, `zod-to-json-schema` provide essential validation and utility.
- Unused dependencies inherited from the template (`diff`, `detect-indent`) have been removed.

## 5. Code Quality & Consistency

- **Strict TypeScript:** Using the strictest compiler options (`strict: true`, etc.).
- **Rigorous Linting:** Employing ESLint with recommended and strict type-checked rules.
- **Consistent Formatting:** Enforced by Prettier.
- **Comprehensive Testing:** Aiming for high test coverage (currently ~95%) using Vitest, with a 100% threshold configured.

## 6. Security Focus

- Path traversal prevention is critical. All file paths are resolved relative to the project root and validated.

## 7. No Sponsorship

This project does not accept financial contributions, and all related information has been removed.
