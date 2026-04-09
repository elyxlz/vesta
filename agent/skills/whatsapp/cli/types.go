package main

import (
	"time"
)

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
