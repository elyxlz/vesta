package main

import (
	"context"
	"fmt"
	"log"
	"time"

	_ "github.com/mattn/go-sqlite3"
	"go.mau.fi/whatsmeow"
	"go.mau.fi/whatsmeow/store/sqlstore"
	"go.mau.fi/whatsmeow/types"
	waLog "go.mau.fi/whatsmeow/util/log"
)

func main() {
	fmt.Println("=== EXTREME GROUP REACTION TEST - TRY EVERYTHING! ===")

	// Setup
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

	// Test data
	groupChat := "120363420369811560@g.us"
	groupMsgID := "3EB03B5AE560B928611AE1"

	groupChatJID, _ := types.ParseJID(groupChat)

	fmt.Printf("Connected! Client ID: %s\n", client.Store.ID)
	fmt.Printf("Testing group: %s\n", groupChat)
	fmt.Printf("Message ID: %s\n", groupMsgID)

	// EXTREME CREATIVE ATTEMPTS - TRY EVERYTHING!

	// Attempt 1: ToNonAD (original approach)
	fmt.Println("\n🔥 Attempt 1: ToNonAD()")
	testGroupReaction(client, groupChatJID, groupMsgID, "1️⃣", client.Store.ID.ToNonAD())
	time.Sleep(2 * time.Second)

	// Attempt 2: Full client JID (what we tried)
	fmt.Println("\n🔥 Attempt 2: Full Client JID")
	testGroupReaction(client, groupChatJID, groupMsgID, "2️⃣", *client.Store.ID)
	time.Sleep(2 * time.Second)

	// Attempt 3: Group JID as sender (crazy idea)
	fmt.Println("\n🔥 Attempt 3: Group JID as sender")
	testGroupReaction(client, groupChatJID, groupMsgID, "3️⃣", groupChatJID)
	time.Sleep(2 * time.Second)

	// Attempt 4: Try different device ID patterns
	fmt.Println("\n🔥 Attempt 4: Different device ID patterns")

	// Try :0 instead of :1
	customJID1 := types.NewJID(client.Store.ID.User, client.Store.ID.Server)
	customJID1.Device = 0
	testGroupReaction(client, groupChatJID, groupMsgID, "4️⃣", customJID1)
	time.Sleep(2 * time.Second)

	// Attempt 5: Try the actual message sender's JID from logs (68569270337562:41@lid)
	fmt.Println("\n🔥 Attempt 5: Message sender's JID")
	messageSenderJID, _ := types.ParseJID("68569270337562:41@lid")
	testGroupReaction(client, groupChatJID, groupMsgID, "5️⃣", messageSenderJID)
	time.Sleep(2 * time.Second)

	// Attempt 6: Try the message sender without device ID
	fmt.Println("\n🔥 Attempt 6: Message sender ToNonAD")
	testGroupReaction(client, groupChatJID, groupMsgID, "6️⃣", messageSenderJID.ToNonAD())
	time.Sleep(2 * time.Second)

	// Attempt 7: Try creating a JID with 'g.us' server
	fmt.Println("\n🔥 Attempt 7: Custom JID with g.us server")
	customGroupJID := types.NewJID(client.Store.ID.User, "g.us")
	testGroupReaction(client, groupChatJID, groupMsgID, "7️⃣", customGroupJID)
	time.Sleep(2 * time.Second)

	// Attempt 8: Try the client with 'lid' server like the group sender
	fmt.Println("\n🔥 Attempt 8: Client JID with lid server")
	customLidJID := types.NewJID(client.Store.ID.User, "lid")
	customLidJID.Device = 1
	testGroupReaction(client, groupChatJID, groupMsgID, "8️⃣", customLidJID)
	time.Sleep(2 * time.Second)

	// Attempt 9: Empty sender (let WhatsApp decide)
	fmt.Println("\n🔥 Attempt 9: Empty sender JID")
	emptyJID := types.EmptyJID
	testGroupReaction(client, groupChatJID, groupMsgID, "9️⃣", emptyJID)
	time.Sleep(2 * time.Second)

	// Attempt 10: NUCLEAR OPTION - Try sending to different variations of group JID
	fmt.Println("\n🔥 Attempt 10: Different group JID formats")

	// Try group admin as target
	adminJID := types.NewJID("120363420369811560", "s.whatsapp.net")
	testGroupReaction(client, adminJID, groupMsgID, "🔟", client.Store.ID.ToNonAD())

	fmt.Println("\n=== EXTREME TEST COMPLETED! ===")
	fmt.Println("Check your group chat - which emojis appeared?")

	client.Disconnect()
}

func testGroupReaction(client *whatsmeow.Client, chatJID types.JID, messageID string, emoji string, senderJID types.JID) {
	fmt.Printf("  📱 Chat: %s\n", chatJID)
	fmt.Printf("  📧 Message: %s\n", messageID)
	fmt.Printf("  😀 Emoji: %s\n", emoji)
	fmt.Printf("  👤 Sender: %s\n", senderJID)

	reactionMsg := client.BuildReaction(chatJID, senderJID, messageID, emoji)
	fmt.Printf("  🔧 Reaction: %+v\n", reactionMsg)

	resp, err := client.SendMessage(context.Background(), chatJID, reactionMsg)

	if err != nil {
		fmt.Printf("  ❌ ERROR: %v\n", err)
	} else {
		fmt.Printf("  ✅ SUCCESS: ID=%s\n", resp.ID)
	}
	fmt.Println()
}