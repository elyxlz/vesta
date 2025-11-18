# Introduction

Welcome to the PDF Reader MCP Server documentation!

This server provides a secure and efficient way for AI agents (like Cline) using the Model Context Protocol (MCP) to interact with PDF files located within a user's project directory.

## What Problem Does It Solve?

AI agents often need information from PDFs (reports, invoices, manuals). Directly feeding PDF content is impractical due to format and size. This server offers specific tools to extract:

- Full text content
- Text from specific pages
- Metadata (author, title, etc.)
- Total page count

All interactions happen securely within the defined project boundaries.

## Core Principles

- **Security:** Confined file access.
- **Efficiency:** Structured data retrieval, avoiding large raw content transfer.
- **Simplicity:** Easy integration into MCP-enabled agent workflows.
