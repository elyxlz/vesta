#!/bin/bash

# Test WhatsApp MCP Go server
echo "Testing WhatsApp MCP Go server..."
echo "This will show the QR code for WhatsApp authentication"
echo "Press Ctrl+C to stop after seeing 'WhatsApp MCP server running...'"
echo ""

# Create test data directory
mkdir -p test-data

# Run the server
./whatsapp-mcp --data-dir ./test-data --notifications-dir ./test-notifications