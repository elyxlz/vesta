# Performance

Performance is an important consideration for the PDF Reader MCP Server, especially when dealing with large or complex PDF documents. This page outlines the benchmarking approach and presents results from initial tests.

## Benchmarking Setup

Benchmarks are conducted using the [Vitest](https://vitest.dev/) testing framework's built-in `bench` functionality. The tests measure the number of operations per second (hz) for different scenarios using the `read_pdf` handler.

- **Environment:** Node.js (latest LTS), Windows 11 (as per user environment)
- **Test File:** A sample PDF located at `test/fixtures/sample.pdf`. The exact characteristics of this file (size, page count, complexity) will influence the results.
- **Methodology:** Each scenario is run for a fixed duration (1000ms) to determine the average operations per second. The benchmark code can be found in `test/benchmark/readPdf.bench.ts`.

## Initial Benchmark Results

The following results were obtained on 2025-04-07 using the setup described above:

| Scenario                         | Operations per Second (hz) | Relative Speed |
| :------------------------------- | :------------------------- | :------------- |
| Handle Non-Existent File         | ~12,933                    | Fastest        |
| Get Full Text                    | ~5,575                     |                |
| Get Specific Page (Page 1)       | ~5,329                     |                |
| Get Specific Pages (Pages 1 & 2) | ~5,242                     |                |
| Get Metadata & Page Count        | ~4,912                     | Slowest        |

_(Higher hz indicates better performance)_

**Interpretation:**

- Handling errors for non-existent files is the fastest operation as it involves minimal I/O and no PDF parsing.
- Extracting the full text was slightly faster than extracting specific pages or just metadata/page count in this particular test run. This might be influenced by the specific structure of `sample.pdf` and potential caching mechanisms within the `pdfjs-dist` library.
- Extracting only metadata and page count was slightly slower than full text extraction for this file.

**Note:** These results are specific to the `sample.pdf` file and the testing environment used. Performance with different PDFs (varying sizes, complexities, versions, or structures) may differ significantly.

## Future Benchmarking Goals

Further benchmarks are planned to measure:

- **Parsing Time:** Time taken to load and parse PDFs of varying sizes (e.g., 1 page, 10 pages, 100 pages, 1000 pages).
- **Text Extraction Speed:** More detailed analysis across different page ranges and document structures.
- **Memory Usage:** Peak memory consumption during processing of different PDF sizes.
- **URL vs. Local File:** Performance difference between processing local files and downloading/processing from URLs.
- **Comparison:** Comparison with other PDF processing methods or libraries, if applicable.

Results will be updated here as more comprehensive testing is completed.
