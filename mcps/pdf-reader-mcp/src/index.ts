#!/usr/bin/env node

import * as fs from 'node:fs';
import * as path from 'node:path';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ErrorCode,
  ListToolsRequestSchema,
  McpError,
} from '@modelcontextprotocol/sdk/types.js';
import type { z } from 'zod'; // Import Zod
import { zodToJsonSchema } from 'zod-to-json-schema';
// Import the aggregated tool definitions
import { allToolDefinitions } from './handlers/index.js';

// --- Context for passing data directory to handlers ---
export interface PdfReaderContext {
  dataDir: string;
  logDir: string;
}

// Module-level context (initialized in main)
// Note: This is the Node.js/TypeScript equivalent of Python FastMCP's lifespan pattern.
// Since the MCP SDK for TypeScript doesn't have a built-in context injection mechanism,
// we use module-level state initialized once during server startup.
let serverContext: PdfReaderContext | null = null;

export const getServerContext = (): PdfReaderContext => {
  if (!serverContext) {
    throw new Error('Server context not initialized');
  }
  return serverContext;
};

// --- Parse CLI Arguments ---
const parseCliArgs = (): PdfReaderContext => {
  const args = process.argv.slice(2);
  let dataDir: string | undefined;
  let logDir: string | undefined;

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--data-dir' && i + 1 < args.length) {
      dataDir = args[i + 1];
      i++;
    } else if (args[i] === '--log-dir' && i + 1 < args.length) {
      logDir = args[i + 1];
      i++;
    }
  }

  if (!dataDir) {
    throw new Error('--data-dir argument is required');
  }
  if (!logDir) {
    throw new Error('--log-dir argument is required');
  }

  // Resolve and create directories
  const resolvedDataDir = path.resolve(dataDir);
  const resolvedLogDir = path.resolve(logDir);

  fs.mkdirSync(resolvedDataDir, { recursive: true });
  fs.mkdirSync(resolvedLogDir, { recursive: true });

  return {
    dataDir: resolvedDataDir,
    logDir: resolvedLogDir,
  };
};

// --- Server Setup ---

const server = new Server(
  {
    name: 'pdf-reader-mcp',
    version: '1.3.0',
    description:
      'MCP Server for reading PDF files and extracting text, metadata, images, and page information.',
  },
  {
    capabilities: { tools: {} },
  }
);

// Helper function to convert Zod schema to JSON schema for MCP
// Use 'unknown' instead of 'any' for better type safety, although casting is still needed for the SDK
const generateInputSchema = (schema: z.ZodType<unknown>): object => {
  // Need to cast as 'unknown' then 'object' because zodToJsonSchema might return slightly incompatible types for MCP SDK
  return zodToJsonSchema(schema, { target: 'openApi3' }) as unknown as object;
};

server.setRequestHandler(ListToolsRequestSchema, () => {
  // Removed unnecessary async
  // Removed log
  // Map the aggregated definitions to the format expected by the SDK
  const availableTools = allToolDefinitions.map((def) => ({
    name: def.name,
    description: def.description,
    inputSchema: generateInputSchema(def.schema), // Generate JSON schema from Zod schema
  }));
  return { tools: availableTools };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  // Use imported handlers
  // Find the tool definition by name and call its handler
  const toolDefinition = allToolDefinitions.find((def) => def.name === request.params.name);

  if (!toolDefinition) {
    throw new McpError(ErrorCode.MethodNotFound, `Unknown tool: ${request.params.name}`);
  }

  // Call the handler associated with the found definition
  // The handler itself will perform Zod validation on the arguments
  return toolDefinition.handler(request.params.arguments);
});

// --- Server Start ---

async function main(): Promise<void> {
  // Parse CLI arguments and initialize context
  serverContext = parseCliArgs();
  console.error(
    `[PDF Reader MCP] Initialized with data-dir: ${serverContext.dataDir}, log-dir: ${serverContext.logDir}`
  );

  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('[PDF Reader MCP] Server running on stdio');
}

main().catch((error: unknown) => {
  // Specify 'unknown' type for catch variable
  console.error('[PDF Reader MCP] Server error:', error);
  process.exit(1);
});
