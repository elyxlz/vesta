// File utilities for saving PDF content to disk
import * as crypto from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';

const PDF_SAVE_SUBDIR = 'pdfs';
const LONG_CONTENT_WARNING_THRESHOLD = 100000; // characters

/**
 * Sanitize a string to be filesystem-safe
 */
export const sanitizeFilename = (value: string): string => {
  const sanitized = value.replace(/[^a-zA-Z0-9]/g, '_').replace(/_+/g, '_').trim();
  return sanitized || 'pdf';
};

/**
 * Generate timestamp in format YYYYMMDDTHHMMSS
 */
export const generateTimestamp = (): string => {
  const now = new Date();
  return now
    .toISOString()
    .replace(/[-:]/g, '')
    .replace(/\.\d{3}Z$/, '');
};

/**
 * Prepare output path for PDF content
 */
export const preparePdfOutputPath = (
  dataDir: string,
  sourceDescription: string,
  savePath?: string
): string => {
  if (savePath) {
    const resolved = path.resolve(savePath);
    const dir = path.dirname(resolved);
    fs.mkdirSync(dir, { recursive: true });
    return resolved;
  }

  const baseDir = path.join(dataDir, PDF_SAVE_SUBDIR);
  fs.mkdirSync(baseDir, { recursive: true });

  const timestamp = generateTimestamp();
  const sanitizedSource = sanitizeFilename(sourceDescription);

  // Add hash-based ID fragment for uniqueness (similar to microsoft-mcp's email_id)
  const hash = crypto.createHash('sha256').update(sourceDescription).digest('hex');
  const idFragment = hash.slice(0, 8);

  const filename = `${timestamp}_${sanitizedSource.slice(0, 40)}_${idFragment}.txt`;

  return path.join(baseDir, filename);
};

/**
 * Save text content to file and return metadata
 */
export const saveContentToFile = (
  filePath: string,
  content: string
): {
  content_saved_to: string;
  content_saved_size: number;
  content_length: number;
  warnings?: string[];
} => {
  try {
    fs.writeFileSync(filePath, content, 'utf-8');
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : String(error);
    throw new Error(`Failed to save PDF content to ${filePath}: ${errorMsg}`);
  }

  let stats;
  try {
    stats = fs.statSync(filePath);
  } catch (error) {
    // File was written but can't stat it - use content length as fallback
    stats = { size: Buffer.byteLength(content, 'utf-8') };
  }

  const result = {
    content_saved_to: filePath,
    content_saved_size: stats.size,
    content_length: content.length,
  };

  if (content.length > LONG_CONTENT_WARNING_THRESHOLD) {
    return {
      ...result,
      warnings: [
        `Content is ${content.length} characters; inspect ${filePath} and grep/crop/filter before pasting snippets to avoid overflowing context.`,
      ],
    };
  }

  return result;
};
