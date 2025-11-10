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

func validateDirectory(path, paramName string) error {
	if path == "" {
		return fmt.Errorf("Error: --%s is required", paramName)
	}
	return nil
}

func main() {
	// Parse command line flags
	var dataDir string
	var logDir string
	var notificationsDir string

	flag.StringVar(&dataDir, "data-dir", "", "Directory for storing persistent data (required)")
	flag.StringVar(&logDir, "log-dir", "", "Directory for storing logs (required)")
	flag.StringVar(&notificationsDir, "notifications-dir", "", "Directory for writing notifications (optional)")
	flag.Parse()

	// Validate required parameters
	if err := validateDirectory(dataDir, "data-dir"); err != nil {
		fmt.Fprintln(os.Stderr, err)
		flag.Usage()
		os.Exit(1)
	}

	if err := validateDirectory(logDir, "log-dir"); err != nil {
		fmt.Fprintln(os.Stderr, err)
		flag.Usage()
		os.Exit(1)
	}

	// Resolve paths
	absDataDir, err := filepath.Abs(dataDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error resolving data directory: %v\n", err)
		os.Exit(1)
	}
	dataDir = absDataDir

	absLogDir, err := filepath.Abs(logDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error resolving log directory: %v\n", err)
		os.Exit(1)
	}
	logDir = absLogDir

	if notificationsDir != "" {
		absNotifDir, err := filepath.Abs(notificationsDir)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error resolving notifications directory: %v\n", err)
			os.Exit(1)
		}
		notificationsDir = absNotifDir
	}

	// Create and validate directories
	if err := os.MkdirAll(dataDir, 0755); err != nil {
		fmt.Fprintf(os.Stderr, "Error creating data directory: %v\n", err)
		os.Exit(1)
	}

	// Test data-dir writability
	testFile := filepath.Join(dataDir, ".write_test")
	if err := os.WriteFile(testFile, []byte("test"), 0644); err != nil {
		fmt.Fprintf(os.Stderr, "Error: --data-dir directory is not writable: %s (%v)\n", dataDir, err)
		os.Exit(1)
	}
	os.Remove(testFile)

	if err := os.MkdirAll(logDir, 0755); err != nil {
		fmt.Fprintf(os.Stderr, "Error creating log directory: %v\n", err)
		os.Exit(1)
	}

	// Test log-dir writability
	testFile = filepath.Join(logDir, ".write_test")
	if err := os.WriteFile(testFile, []byte("test"), 0644); err != nil {
		fmt.Fprintf(os.Stderr, "Error: --log-dir directory is not writable: %s (%v)\n", logDir, err)
		os.Exit(1)
	}
	os.Remove(testFile)

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