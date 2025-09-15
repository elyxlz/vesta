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
	fmt.Println("=== WORKING REACTIONS TEST ===")

	// Setup WhatsApp client
	ctx := context.Background()
	dbLog := waLog.Stdout("Database", "WARN", true)
	container, err := sqlstore.New(ctx, "sqlite3", "file:store/whatsapp.db?_foreign_keys=on", dbLog)
	if err != nil {
		log.Fatalf("Failed to create database: %v", err)
	}

	deviceStore, err := container.GetFirstDevice(ctx)
	if err != nil {
		log.Fatalf("Failed to get device: %v", err)
	}

	clientLog := waLog.Stdout("Client", "INFO", true)
	client := whatsmeow.NewClient(deviceStore, clientLog)

	if client.Store.ID == nil {
		log.Fatal("No stored session found")
	}

	err = client.Connect()
	if err != nil {
		log.Fatalf("Failed to connect: %v", err)
	}

	// Test messages from logs
	privateChat := "393483589770@s.whatsapp.net"
	privateMsgID := "3EB06E44DD48F5C498519A"

	groupChat := "120363420369811560@g.us"
	groupMsgID := "3EB00A86CF88D042672AB2"
	groupSender := "68569270337562@lid" // Message sender from logs

	fmt.Printf("Connected! Client: %s\n\n", client.Store.ID)

	// WORKING SOLUTION 1: Private Chat
	fmt.Println("✅ PRIVATE CHAT REACTION (Working Solution)")
	fmt.Println("Method: Use chat JID as sender → fromMe:false")

	privateChatJID, _ := types.ParseJID(privateChat)
	testReaction(client, privateChatJID, privateMsgID, "🔥", privateChatJID, "Private")

	// WORKING SOLUTION 2: Group Chat
	fmt.Println("\n✅ GROUP CHAT REACTION (Working Solution)")
	fmt.Println("Method: Use message sender's JID → fromMe:false, participant:sender")

	groupChatJID, _ := types.ParseJID(groupChat)
	messageSenderJID, _ := types.ParseJID(groupSender)
	testReaction(client, groupChatJID, groupMsgID, "⚡", messageSenderJID, "Group")

	fmt.Println("\n🎉 BOTH REACTIONS SENT!")
	fmt.Println("Check your chats:")
	fmt.Println("- Private: Look for 🔥 on your 'xx' message")
	fmt.Println("- Group: Look for ⚡ on your 'xx' message")

	client.Disconnect()
}

func testReaction(client *whatsmeow.Client, chatJID types.JID, messageID string, emoji string, senderJID types.JID, chatType string) {
	fmt.Printf("  📱 %s Chat: %s\n", chatType, chatJID)
	fmt.Printf("  📧 Message ID: %s\n", messageID)
	fmt.Printf("  😀 Emoji: %s\n", emoji)
	fmt.Printf("  👤 Sender: %s\n", senderJID)

	// Build and send reaction
	reactionMsg := client.BuildReaction(chatJID, senderJID, messageID, emoji)
	resp, err := client.SendMessage(context.Background(), chatJID, reactionMsg)

	if err != nil {
		fmt.Printf("  ❌ ERROR: %v\n", err)
	} else {
		fmt.Printf("  ✅ SUCCESS: %+v\n", resp)
	}
}