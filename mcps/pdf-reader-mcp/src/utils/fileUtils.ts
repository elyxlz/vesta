// File utilities for saving PDF content to disk
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
    .replace(/\.\d{3}Z$/, '')
    .replace('T', 'T');
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
  const filename = `${timestamp}_${sanitizedSource.slice(0, 40)}.txt`;

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
  fs.writeFileSync(filePath, content, 'utf-8');
  const stats = fs.statSync(filePath);

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
