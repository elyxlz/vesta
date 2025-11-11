# Testing Strategy

Robust testing is essential for ensuring the reliability, correctness, and security of the PDF Reader MCP Server. We employ a multi-faceted testing approach using Vitest.

## Framework: Vitest

We use [Vitest](https://vitest.dev/) as our primary testing framework. Its key advantages include:

- **Speed:** Fast execution powered by Vite.
- **Modern Features:** Supports ES Modules, TypeScript out-of-the-box.
- **Compatibility:** Familiar API similar to Jest.
- **Integrated Coverage:** Built-in support for code coverage analysis using `v8` or `istanbul`.

## Goals & Approach

Our testing strategy focuses on:

1.  **High Code Coverage:**

    - **Target:** 100% statement, branch, function, and line coverage.
    - **Configuration:** Enforced via `thresholds` in `vitest.config.ts`.
    - **Current Status:** ~95%. The remaining uncovered lines are primarily in error handling paths that are difficult to trigger due to Zod's upfront validation or represent extreme edge cases. This level is currently accepted.
    - **Tool:** Coverage reports generated using `@vitest/coverage-v8`.

2.  **Correctness & Functionality:**

    - **Unit Tests:** (Currently minimal, focus is on integration) Could test utility functions like `pathUtils` in isolation.
    - **Integration Tests:** The primary focus is testing the `read_pdf` handler (`test/handlers/readPdf.test.ts`) with mocked dependencies (`pdfjs-dist`, `fs`). These tests verify:
      - Correct parsing of various input arguments (paths, URLs, page selections, flags).
      - Successful extraction of full text, specific page text, metadata, and page counts.
      - Handling of multiple sources (local and URL) within a single request.
      - Correct formatting of the JSON response.
      - Graceful error handling for invalid inputs (caught by Zod or handler logic).
      - Correct error reporting for file-not-found errors.
      - Correct error reporting for PDF loading/parsing failures (mocked).
      - Proper handling of warnings (e.g., requested pages out of bounds).
    - **Security:** Path resolution logic (`resolvePath`) is tested separately (`test/pathUtils.test.ts`) to ensure it prevents path traversal and correctly handles relative paths within the project root.

3.  **Reliability & Consistency:**
    - Tests are designed to be independent and repeatable.
    - Mocking is used extensively to isolate the handler logic from external factors.

## Running Tests

Use the following npm scripts:

- **`npm test`**: Run all tests once.
- **`npm run test:watch`**: Run tests in an interactive watch mode, re-running on file changes.
- **`npm run test:cov`**: Run all tests and generate a detailed coverage report in the `./coverage/` directory (view `index.html` in that directory for an interactive report). This command will fail if coverage thresholds are not met.

## Test File Structure

- Tests reside in the `test/` directory, mirroring the `src/` structure.
- Handler tests are in `test/handlers/`.
- Utility tests are in `test/utils/`.

## Future Improvements

- Consider adding end-to-end tests using a test MCP client/host.
- Explore property-based testing for more robust input validation checks.
