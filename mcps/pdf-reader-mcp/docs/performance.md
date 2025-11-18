# Performance

Performance is a key consideration for the PDF Reader MCP Server, as slow responses can negatively impact the interaction flow of AI agents.

## Core Library: `pdfjs-dist`

The server relies on Mozilla's [pdf.js](https://mozilla.github.io/pdf.js/) (specifically the `pdfjs-dist` distribution) for the heavy lifting of PDF parsing. This library is widely used and generally considered performant for standard PDF documents. However, performance can vary depending on:

- **PDF Complexity:** Documents with many pages, complex graphics, large embedded fonts, or non-standard structures may take longer to parse.
- **Requested Data:** Extracting full text from a very large document will naturally take longer than just retrieving metadata or the page count. Requesting text from only a few specific pages is usually more efficient than extracting the entire text.
- **Server Resources:** The performance will also depend on the CPU and memory resources available to the Node.js process running the server.

## Asynchronous Operations

All potentially long-running operations, including file reading (for local PDFs), network requests (for URL PDFs), and PDF parsing itself, are handled asynchronously using `async/await`. This prevents the server from blocking the Node.js event loop and allows it to handle other requests or tasks concurrently (though typically an MCP server handles one request at a time from its host).

## Benchmarking (Planned)

_(Section to be added)_

Formal benchmarking is planned to quantify the performance characteristics of the `read_pdf` tool under various conditions.

**Goals:**

- Measure the time taken to extract metadata, page count, specific pages, and full text for PDFs of varying sizes and complexities.
- Compare the performance of processing local files vs. URLs (network latency will be a factor for URLs).
- Identify potential bottlenecks within the handler logic or the `pdfjs-dist` library usage.
- Establish baseline performance metrics to track potential regressions in the future.

**Tools:**

- We plan to use [Vitest's built-in benchmarking](https://vitest.dev/guide/features.html#benchmarking) (`bench` function) or a dedicated library like [`tinybench`](https://github.com/tinylibs/tinybench).

Benchmark results will be published in this section once available.

## Current Optimization Considerations

- **Lazy Loading:** The `pdfjs-dist` library loads pages on demand when `pdfDocument.getPage()` is called. This means that if only metadata or page count is requested, the entire document's page content doesn't necessarily need to be parsed immediately.
- **Selective Extraction:** The ability to request specific pages (`pages` parameter) allows agents to avoid the cost of extracting text from the entire document if only a small portion is needed.

_(This section will be updated with concrete data and findings as benchmarking is performed.)_
