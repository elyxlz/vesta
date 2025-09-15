package main

import (
	"context"
	"fmt"
	"log"

	_ "github.com/mattn/go-sqlite3"
	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	waLog "go.mau.fi/whatsmeow/util/log"
)

func main() {
	fmt.Println("=== WhatsApp Reaction Test ===")

	// Test data from logs
	privateChat := "393483589770@s.whatsapp.net"
	privateMsgID := "3EB038CA21C7D86F090A3D"

	groupChat := "120363420369811560@g.us"
	groupMsgID := "3EB0CD6CC934B7259CBF37"

	// Setup database
	ctx := context.Background()
	dbLog := waLog.Stdout("Database", "WARN", true)
	container, err := sqlstore.New(ctx, "sqlite3", "file:store/whatsapp.db?_foreign_keys=on", dbLog)
	if err != nil {
		log.Fatalf("Failed to create database: %v", err)
	}

	// Get device
	deviceStore, err := container.GetFirstDevice(ctx)
	if err != nil {
		log.Fatalf("Failed to get device: %v", err)
	}

	clientLog := waLog.Stdout("Client", "INFO", true)
	client := whatsmeow.NewClient(deviceStore, clientLog)

	// Connect
	if client.Store.ID == nil {
		log.Fatal("No stored session found")
	}

	err = client.Connect()
	if err != nil {
		log.Fatalf("Failed to connect: %v", err)
	}

	fmt.Printf("Connected! Client ID: %s\n", client.Store.ID)
	fmt.Printf("Client ID (ToNonAD): %s\n", client.Store.ID.ToNonAD())

	// Test 1: Private chat reaction with different sender configurations
	fmt.Println("\n=== TEST 1: Private Chat Reactions ===")

	privateChatJID, _ := types.ParseJID(privateChat)

	// Try 1a: Use ToNonAD() as sender
	fmt.Println("Test 1a: Private chat with ToNonAD() sender")
	testReaction(client, privateChatJID, privateMsgID, "🅰️", client.Store.ID.ToNonAD())

	// Try 1b: Use full client ID as sender
	fmt.Println("Test 1b: Private chat with full client ID sender")
	testReaction(client, privateChatJID, privateMsgID, "🔵", *client.Store.ID)

	// Try 1c: Use chat JID as sender (wrong but let's try)
	fmt.Println("Test 1c: Private chat with chat JID as sender")
	testReaction(client, privateChatJID, privateMsgID, "🟡", privateChatJID)

	// Test 2: Group chat reaction with different sender configurations
	fmt.Println("\n=== TEST 2: Group Chat Reactions ===")

	groupChatJID, _ := types.ParseJID(groupChat)

	// Try 2a: Use ToNonAD() as sender
	fmt.Println("Test 2a: Group chat with ToNonAD() sender")
	testReaction(client, groupChatJID, groupMsgID, "🅱️", client.Store.ID.ToNonAD())

	// Try 2b: Use full client ID as sender
	fmt.Println("Test 2b: Group chat with full client ID sender")
	testReaction(client, groupChatJID, groupMsgID, "🔴", *client.Store.ID)

	fmt.Println("\n=== All tests completed! ===")

	client.Disconnect()
}

func testReaction(client *whatsmeow.Client, chatJID types.JID, messageID string, emoji string, senderJID types.JID) {
	fmt.Printf("  Chat: %s\n", chatJID)
	fmt.Printf("  Message ID: %s\n", messageID)
	fmt.Printf("  Emoji: %s\n", emoji)
	fmt.Printf("  Sender: %s\n", senderJID)

	// Build reaction message
	reactionMsg := client.BuildReaction(chatJID, senderJID, messageID, emoji)
	fmt.Printf("  Reaction message: %+v\n", reactionMsg)

	// Send reaction
	resp, err := client.SendMessage(context.Background(), chatJID, reactionMsg)

	if err != nil {
		fmt.Printf("  ❌ ERROR: %v\n", err)
	} else {
		fmt.Printf("  ✅ SUCCESS: %+v\n", resp)
	}
	fmt.Println()
}