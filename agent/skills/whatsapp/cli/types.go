package main

import "time"

type Message struct {
	ID          string    `json:"id"`
	ChatJID     string    `json:"-"`
	ChatName    string    `json:"chat_name,omitempty"`
	Sender      string    `json:"sender"`
	Content     string    `json:"content"`
	Timestamp   time.Time `json:"timestamp"`
	IsFromMe    bool      `json:"is_from_me"`
	IsForwarded bool      `json:"is_forwarded"`
	MediaType   string    `json:"media_type,omitempty"`
	Filename    string    `json:"filename,omitempty"`
	// Receipts for messages we sent. Recorded by the daemon since the LID split was fixed, but
	// until now never surfaced by list-messages, so every reader of this CLI was blind to whether
	// the user had opened anything. omitempty because an inbound message has no receipt of ours.
	DeliveryStatus    string     `json:"delivery_status,omitempty"`
	DeliveryTimestamp *time.Time `json:"delivery_timestamp,omitempty"`
}

type Chat struct {
	JID             string    `json:"-"`
	Name            string    `json:"name,omitempty"`
	LastMessageTime time.Time `json:"last_message_time,omitempty"`
	LastMessage     string    `json:"last_message,omitempty"`
	LastSender      string    `json:"last_sender,omitempty"`
	LastIsFromMe    bool      `json:"last_is_from_me,omitempty"`
	IsGroup         bool      `json:"is_group"`
}

type Contact struct {
	PhoneNumber string `json:"phone_number"`
	Name        string `json:"name,omitempty"`
	JID         string `json:"-"`
	IsManual    bool   `json:"is_manual,omitempty"`
}

type StoreMessageParams struct {
	ID            string
	ChatJID       string
	Sender        string
	Content       string
	Timestamp     time.Time
	IsFromMe      bool
	IsForwarded   bool
	MediaType     string
	Filename      string
	URL           string
	MediaKey      []byte
	FileSHA256    []byte
	FileEncSHA256 []byte
	FileLength    uint64
}

type NotifContext struct {
	NotifDir string
	ChatJID  string
	ChatName string
	// ContactName is the one identity field a notification carries: the saved contact name when the
	// sender is saved, otherwise the best human identifier (a formatted number or JID). It is set for
	// both direct and group chats; in a group, ChatName names the group and this names the participant.
	ContactName  string
	ContactPhone string
	Instance     string
	ContactSaved bool
	IsDirectChat bool
	// NameSharedWithGroup marks a saved contact whose name a group also holds, so the reply keeps
	// the chat JID rather than an ambiguous name that could resolve to the group.
	NameSharedWithGroup bool
}

type MediaInfo struct {
	MessageID     string
	ChatJID       string
	MediaType     string
	Filename      string
	URL           string
	MediaKey      []byte
	FileSHA256    []byte
	FileEncSHA256 []byte
	FileLength    uint64
}
