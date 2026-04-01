package main

import (
	"time"
)

type Message struct {
	ID        int64     `json:"id"`
	ChatID    int64     `json:"-"`
	ChatName  string    `json:"chat_name,omitempty"`
	Sender    string    `json:"sender"`
	Content   string    `json:"content"`
	Timestamp time.Time `json:"timestamp"`
	IsFromMe  bool      `json:"is_from_me"`
	MediaType string    `json:"media_type,omitempty"`
	Filename  string    `json:"filename,omitempty"`
	ReplyToID int64     `json:"reply_to_id,omitempty"`
}

type Chat struct {
	ID              int64     `json:"id"`
	Name            string    `json:"name,omitempty"`
	ChatType        string    `json:"chat_type"` // "private", "group", "supergroup", "channel"
	LastMessageTime time.Time `json:"last_message_time,omitempty"`
	LastMessage     string    `json:"last_message,omitempty"`
	LastSender      string    `json:"last_sender,omitempty"`
	LastIsFromMe    bool      `json:"last_is_from_me,omitempty"`
}

type Contact struct {
	ChatID   int64  `json:"chat_id"`
	Name     string `json:"name,omitempty"`
	Username string `json:"username,omitempty"`
	IsManual bool   `json:"is_manual,omitempty"`
}
