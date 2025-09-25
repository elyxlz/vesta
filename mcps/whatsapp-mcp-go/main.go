package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	waLog "go.mau.fi/whatsmeow/util/log"
)

func main() {
	// Parse command line flags
	var dataDir string
	var notificationsDir string

	flag.StringVar(&dataDir, "data-dir", "", "Directory for storing persistent data (required)")
	flag.StringVar(&notificationsDir, "notifications-dir", "", "Directory for writing notifications (optional)")
	flag.Parse()

	if dataDir == "" {
		fmt.Fprintln(os.Stderr, "Error: --data-dir is required")
		flag.Usage()
		os.Exit(1)
	}

	// Resolve paths
	dataDir, err := filepath.Abs(dataDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error resolving data directory: %v\n", err)
		os.Exit(1)
	}

	if notificationsDir != "" {
		notificationsDir, err = filepath.Abs(notificationsDir)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error resolving notifications directory: %v\n", err)
			os.Exit(1)
		}
	}

	// Create directories if they don't exist
	if err := os.MkdirAll(dataDir, 0755); err != nil {
		fmt.Fprintf(os.Stderr, "Error creating data directory: %v\n", err)
		os.Exit(1)
	}

	if notificationsDir != "" {
		if err := os.MkdirAll(notificationsDir, 0755); err != nil {
			fmt.Fprintf(os.Stderr, "Error creating notifications directory: %v\n", err)
			os.Exit(1)
		}
	}

	// Set up logger - output to stderr so we can see it
	logger := waLog.Stdout("WhatsApp", "DEBUG", true)

	// Initialize WhatsApp client
	fmt.Fprintln(os.Stderr, "Initializing WhatsApp client...")
	wac, err := NewWhatsAppClient(dataDir, notificationsDir, logger)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to initialize WhatsApp client: %v\n", err)
		os.Exit(1)
	}

	// Start WhatsApp connection (non-blocking)
	fmt.Fprintln(os.Stderr, "Starting WhatsApp connection...")
	if err := wac.Connect(); err != nil {
		fmt.Fprintf(os.Stderr, "Failed to start WhatsApp connection: %v\n", err)
		os.Exit(1)
	}

	fmt.Fprintf(os.Stderr, "✓ WhatsApp client initialized. Data directory: %s\n", dataDir)
	if notificationsDir != "" {
		fmt.Fprintf(os.Stderr, "Notifications directory: %s\n", notificationsDir)
	}

	// Check initial auth status
	if !wac.IsAuthenticated() {
		fmt.Fprintln(os.Stderr, "⚠ WhatsApp not authenticated. Use the 'authenticate_whatsapp' tool to get QR code.")
	}

	// Create MCP server
	mcpServer := mcp.NewServer(&mcp.Implementation{
		Name:    "whatsapp-mcp",
		Version: "1.0.0",
	}, nil)

	// Register all tools
	RegisterTools(mcpServer, wac)

	// Set up signal handling for graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Create context for server
	ctx, cancel := context.WithCancel(context.Background())

	// Handle shutdown in background
	go func() {
		<-sigChan
		fmt.Fprintln(os.Stderr, "\nShutting down...")
		cancel()
		wac.Disconnect()
	}()

	// Run MCP server on stdio
	fmt.Fprintln(os.Stderr, "WhatsApp MCP server running...")

	if err := mcpServer.Run(ctx, &mcp.StdioTransport{}); err != nil {
		fmt.Fprintf(os.Stderr, "Server error: %v\n", err)
		wac.Disconnect()
		os.Exit(1)
	}

	wac.Disconnect()
	fmt.Fprintln(os.Stderr, "Server stopped")
}