// PDF reading handler - orchestrates PDF processing workflow

import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';
import { z } from 'zod';
import { getServerContext } from '../index.js';
import {
  buildWarnings,
  extractMetadataAndPageCount,
  extractPageContent,
} from '../pdf/extractor.js';
import { loadPdfDocument } from '../pdf/loader.js';
import { determinePagesToProcess, getTargetPages } from '../pdf/parser.js';
import type { ReadPdfArgs } from '../schemas/readPdf.js';
import { readPdfArgsSchema } from '../schemas/readPdf.js';
import type { ExtractedImage, PdfResultData, PdfSource, PdfSourceResult } from '../types/pdf.js';
import { preparePdfOutputPath, saveContentToFile } from '../utils/fileUtils.js';
import type { ToolDefinition } from './index.js';

/**
 * Process a single PDF source
 */
const processSingleSource = async (
  source: PdfSource,
  options: {
    includeFullText: boolean;
    includeMetadata: boolean;
    includePageCount: boolean;
    includeImages: boolean;
  }
): Promise<PdfSourceResult> => {
  const sourceDescription = source.path ?? source.url ?? 'unknown source';
  let individualResult: PdfSourceResult = { source: sourceDescription, success: false };

  try {
    // Parse target pages
    const targetPages = getTargetPages(source.pages, sourceDescription);

    // Load PDF document
    const { pages: _pages, ...loadArgs } = source;
    const pdfDocument = await loadPdfDocument(loadArgs, sourceDescription);
    const totalPages = pdfDocument.numPages;

    // Extract metadata and page count
    const metadataOutput = await extractMetadataAndPageCount(
      pdfDocument,
      options.includeMetadata,
      options.includePageCount
    );

    const output: PdfResultData = { ...metadataOutput };

    // Determine pages to process
    const { pagesToProcess, invalidPages } = determinePagesToProcess(
      targetPages,
      totalPages,
      options.includeFullText
    );

    // Add warnings for invalid pages
    const warnings = buildWarnings(invalidPages, totalPages);
    if (warnings.length > 0) {
      output.warnings = warnings;
    }

    // Extract content with ordering preserved
    if (pagesToProcess.length > 0) {
      // Use new extractPageContent to preserve Y-coordinate ordering
      const pageContents = await Promise.all(
        pagesToProcess.map((pageNum) =>
          extractPageContent(pdfDocument, pageNum, options.includeImages, sourceDescription)
        )
      );

      // Store page contents for ordered retrieval
      output.page_contents = pageContents.map((items, idx) => ({
        page: pagesToProcess[idx] as number,
        items,
      }));

      // For backward compatibility, also provide text-only outputs
      const extractedPageTexts = pageContents.map((items, idx) => ({
        page: pagesToProcess[idx] as number,
        text: items
          .filter((item) => item.type === 'text')
          .map((item) => item.textContent)
          .join(''),
      }));

      if (targetPages) {
        // Specific pages requested
        output.page_texts = extractedPageTexts;
      } else {
        // Full text requested
        output.full_text = extractedPageTexts.map((p) => p.text).join('\n\n');
      }

      // Extract image metadata for JSON response
      if (options.includeImages) {
        const extractedImages = pageContents
          .flatMap((items) => items.filter((item) => item.type === 'image' && item.imageData))
          .map((item) => item.imageData)
          .filter((img): img is ExtractedImage => img !== undefined);

        if (extractedImages.length > 0) {
          output.images = extractedImages;
        }
      }
    }

    individualResult = { ...individualResult, data: output, success: true };
  } catch (error: unknown) {
    let errorMessage = `Failed to process PDF from ${sourceDescription}.`;

    if (error instanceof McpError) {
      errorMessage = error.message;
    } /* c8 ignore next */ else if (error instanceof Error) {
      errorMessage += ` Reason: ${error.message}`;
    } else {
      errorMessage += ` Unknown error: ${JSON.stringify(error)}`;
    }

    individualResult.error = errorMessage;
    individualResult.success = false;
    individualResult.data = undefined;
  }

  return individualResult;
};

/**
 * Main handler function for read_pdf tool
 * Saves all content to files and returns only metadata
 */
export const handleReadPdfFunc = async (
  args: unknown
): Promise<{
  content: Array<{ type: string; text?: string }>;
}> => {
  let parsedArgs: ReadPdfArgs;

  try {
    parsedArgs = readPdfArgsSchema.parse(args);
  } catch (error: unknown) {
    if (error instanceof z.ZodError) {
      throw new McpError(
        ErrorCode.InvalidParams,
        `Invalid arguments: ${error.issues.map((e: z.ZodIssue) => `${e.path.join('.')} (${e.message})`).join(', ')}`
      );
    }

    /* c8 ignore next */
    const message = error instanceof Error ? error.message : String(error);
    /* c8 ignore next */
    throw new McpError(ErrorCode.InvalidParams, `Argument validation failed: ${message}`);
  }

  const {
    sources,
    include_full_text,
    include_metadata,
    include_page_count,
    include_images,
    save_to_file,
  } = parsedArgs;

  // Get server context for data directory
  const context = getServerContext();

  // Process all sources concurrently
  const results = await Promise.all(
    sources.map((source) =>
      processSingleSource(source, {
        includeFullText: include_full_text,
        includeMetadata: include_metadata,
        includePageCount: include_page_count,
        includeImages: include_images,
      })
    )
  );

  // Build text content from all results
  const contentParts: string[] = [];

  // Add metadata summary
  for (const result of results) {
    contentParts.push(`\n${'='.repeat(80)}\n`);
    contentParts.push(`Source: ${result.source}\n`);
    contentParts.push(`Success: ${result.success}\n`);

    if (result.error) {
      contentParts.push(`Error: ${result.error}\n`);
      continue;
    }

    if (result.data) {
      if (result.data.num_pages !== undefined) {
        contentParts.push(`Pages: ${result.data.num_pages}\n`);
      }
      if (result.data.metadata) {
        contentParts.push(`Metadata: ${JSON.stringify(result.data.metadata, null, 2)}\n`);
      }
      if (result.data.warnings && result.data.warnings.length > 0) {
        contentParts.push(`Warnings:\n${result.data.warnings.map((w) => `  - ${w}`).join('\n')}\n`);
      }
    }

    contentParts.push(`\n${'='.repeat(80)}\n\n`);

    // Add extracted text content
    if (result.success && result.data?.page_contents) {
      for (const pageContent of result.data.page_contents) {
        contentParts.push(`\n--- Page ${pageContent.page} ---\n\n`);
        for (const item of pageContent.items) {
          if (item.type === 'text' && item.textContent) {
            contentParts.push(item.textContent);
          }
        }
        contentParts.push('\n');
      }
    } else if (result.success && result.data?.full_text) {
      contentParts.push(result.data.full_text);
      contentParts.push('\n');
    }
  }

  const fullContent = contentParts.join('');

  // Determine source description for filename
  const sourceDescription =
    sources.length === 1
      ? sources[0]?.path ?? sources[0]?.url ?? 'pdf'
      : `${sources.length}_pdfs`;

  // Save content to file
  const savePath = preparePdfOutputPath(context.dataDir, sourceDescription, save_to_file);
  const saveResult = saveContentToFile(savePath, fullContent);

  // Build response with metadata only (no content)
  const responseData = {
    sources: sources.map((s) => s.path ?? s.url ?? 'unknown'),
    results_summary: results.map((r) => ({
      source: r.source,
      success: r.success,
      num_pages: r.data?.num_pages,
      error: r.error,
    })),
    ...saveResult,
  };

  return {
    content: [
      {
        type: 'text',
        text: JSON.stringify(responseData, null, 2),
      },
    ],
  };
};

// Export the tool definition
export const readPdfToolDefinition: ToolDefinition = {
  name: 'read_pdf',
  description:
    'Extracts content/metadata from PDFs (local/URL) and saves to disk. Content is NEVER returned in response, only file path and metadata. Each source can specify pages to extract.',
  schema: readPdfArgsSchema,
  handler: handleReadPdfFunc,
};
