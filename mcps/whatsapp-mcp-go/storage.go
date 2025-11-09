package main

import (
	"database/sql"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"

	_ "github.com/mattn/go-sqlite3"
)

type MessageStore struct {
	db *sql.DB
}

func NewMessageStore(dataDir string) (*MessageStore, error) {
	dbPath := filepath.Join(dataDir, "messages.db")

	if err := os.MkdirAll(dataDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create data directory: %v", err)
	}

	// Use url.PathEscape to prevent SQL injection via file path
	escapedPath := url.PathEscape(dbPath)
	db, err := sql.Open("sqlite3", fmt.Sprintf("file:%s?_foreign_keys=on", escapedPath))
	if err != nil {
		return nil, fmt.Errorf("failed to open message database: %v", err)
	}

	_, err = db.Exec(`
		CREATE TABLE IF NOT EXISTS chats (
			jid TEXT PRIMARY KEY,
			name TEXT,
			last_message_time TIMESTAMP
		);

		CREATE TABLE IF NOT EXISTS messages (
			id TEXT,
			chat_jid TEXT,
			sender TEXT,
			content TEXT,
			timestamp TIMESTAMP,
			is_from_me BOOLEAN,
			is_forwarded BOOLEAN DEFAULT 0,
			media_type TEXT,
			filename TEXT,
			url TEXT,
			media_key BLOB,
			file_sha256 BLOB,
			file_enc_sha256 BLOB,
			file_length INTEGER,
			PRIMARY KEY (id, chat_jid),
			FOREIGN KEY (chat_jid) REFERENCES chats(jid)
		);

		CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
		CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender);
		CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_jid);
	`)
	if err != nil {
		db.Close()
		return nil, fmt.Errorf("failed to create tables: %v", err)
	}

	return &MessageStore{db: db}, nil
}

func (ms *MessageStore) Close() error {
	return ms.db.Close()
}

func (ms *MessageStore) StoreChat(jid, name string, lastMessageTime time.Time) error {
	_, err := ms.db.Exec(`
		INSERT INTO chats (jid, name, last_message_time)
		VALUES (?, ?, ?)
		ON CONFLICT(jid) DO UPDATE SET
			name = COALESCE(excluded.name, chats.name),
			last_message_time = CASE
				WHEN excluded.last_message_time > chats.last_message_time
				THEN excluded.last_message_time
				ELSE chats.last_message_time
			END
	`, jid, name, lastMessageTime)
	return err
}

func (ms *MessageStore) StoreMessage(
	id, chatJID, sender, content string,
	timestamp time.Time,
	isFromMe, isForwarded bool,
	mediaType, filename, url string,
	mediaKey, fileSHA256, fileEncSHA256 []byte,
	fileLength uint64,
) error {
	_, err := ms.db.Exec(`
		INSERT OR REPLACE INTO messages (
			id, chat_jid, sender, content, timestamp,
			is_from_me, is_forwarded, media_type, filename, url,
			media_key, file_sha256, file_enc_sha256, file_length
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
	`, id, chatJID, sender, content, timestamp, isFromMe, isForwarded,
		mediaType, filename, url, mediaKey, fileSHA256, fileEncSHA256, fileLength)
	return err
}

func (ms *MessageStore) GetChatName(jid string) (string, error) {
	var name sql.NullString
	err := ms.db.QueryRow("SELECT name FROM chats WHERE jid = ?", jid).Scan(&name)
	if err != nil {
		return "", err
	}
	return name.String, nil
}

func (ms *MessageStore) SearchContacts(query string, limit int) ([]Contact, error) {
	if limit == 0 {
		limit = 50
	}

	rows, err := ms.db.Query(`
		SELECT DISTINCT jid, name
		FROM chats
		WHERE (name LIKE ? OR jid LIKE ?)
		AND jid NOT LIKE '%@g.us'
		ORDER BY name
		LIMIT ?
	`, "%"+query+"%", "%"+query+"%", limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	contacts := make([]Contact, 0, limit)
	for rows.Next() {
		var c Contact
		var name sql.NullString
		if err := rows.Scan(&c.JID, &name); err != nil {
			continue
		}
		c.Name = name.String
		if idx := strings.Index(c.JID, "@"); idx > 0 {
			c.PhoneNumber = c.JID[:idx]
		}
		contacts = append(contacts, c)
	}
	return contacts, nil
}

func (ms *MessageStore) ListMessages(
	after, before *time.Time,
	senderPhone, chatJID, query string,
	limit, offset int,
	includeContext bool,
	contextBefore, contextAfter int,
) ([]Message, error) {
	queryBuilder := strings.Builder{}
	queryBuilder.WriteString(`
		SELECT
			m.id, m.chat_jid, c.name, m.sender, m.content,
			m.timestamp, m.is_from_me, m.is_forwarded, m.media_type, m.filename
		FROM messages m
		JOIN chats c ON m.chat_jid = c.jid
		WHERE 1=1
	`)

	args := []interface{}{}

	if after != nil {
		queryBuilder.WriteString(" AND m.timestamp >= ?")
		args = append(args, *after)
	}
	if before != nil {
		queryBuilder.WriteString(" AND m.timestamp <= ?")
		args = append(args, *before)
	}
	if senderPhone != "" {
		queryBuilder.WriteString(" AND m.sender LIKE ?")
		args = append(args, "%"+senderPhone+"%")
	}
	if chatJID != "" {
		queryBuilder.WriteString(" AND m.chat_jid = ?")
		args = append(args, chatJID)
	}
	if query != "" {
		queryBuilder.WriteString(" AND m.content LIKE ?")
		args = append(args, "%"+query+"%")
	}

	queryBuilder.WriteString(" ORDER BY m.timestamp DESC")
	queryBuilder.WriteString(" LIMIT ? OFFSET ?")
	args = append(args, limit, offset)

	rows, err := ms.db.Query(queryBuilder.String(), args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var messages []Message
	for rows.Next() {
		var m Message
		var chatName, mediaType, filename sql.NullString
		if err := rows.Scan(
			&m.ID, &m.ChatJID, &chatName, &m.Sender, &m.Content,
			&m.Timestamp, &m.IsFromMe, &m.IsForwarded, &mediaType, &filename,
		); err != nil {
			continue
		}
		m.ChatName = chatName.String
		m.MediaType = mediaType.String
		m.Filename = filename.String
		messages = append(messages, m)
	}

	return messages, nil
}

func (ms *MessageStore) ListChats(
	query string,
	limit, offset int,
	includeLastMessage bool,
	sortBy string,
) ([]Chat, error) {
	queryBuilder := strings.Builder{}

	if includeLastMessage {
		queryBuilder.WriteString(`
			SELECT
				c.jid, c.name, c.last_message_time,
				m.content, m.sender, m.is_from_me
			FROM chats c
			LEFT JOIN messages m ON c.jid = m.chat_jid
				AND c.last_message_time = m.timestamp
		`)
	} else {
		queryBuilder.WriteString(`
			SELECT
				c.jid, c.name, c.last_message_time,
				NULL, NULL, NULL
			FROM chats c
		`)
	}

	args := []interface{}{}
	if query != "" {
		queryBuilder.WriteString(" WHERE c.name LIKE ?")
		args = append(args, "%"+query+"%")
	}

	if sortBy == "name" {
		queryBuilder.WriteString(" ORDER BY c.name")
	} else {
		queryBuilder.WriteString(" ORDER BY c.last_message_time DESC")
	}

	queryBuilder.WriteString(" LIMIT ? OFFSET ?")
	args = append(args, limit, offset)

	rows, err := ms.db.Query(queryBuilder.String(), args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var chats []Chat
	for rows.Next() {
		var c Chat
		var name, lastMsg, lastSender sql.NullString
		var lastTime sql.NullTime
		var lastIsFromMe sql.NullBool

		if err := rows.Scan(
			&c.JID, &name, &lastTime,
			&lastMsg, &lastSender, &lastIsFromMe,
		); err != nil {
			continue
		}

		c.Name = name.String
		if lastTime.Valid {
			c.LastMessageTime = lastTime.Time
		}
		c.LastMessage = lastMsg.String
		c.LastSender = lastSender.String
		c.LastIsFromMe = lastIsFromMe.Bool
		c.IsGroup = strings.HasSuffix(c.JID, "@g.us")

		chats = append(chats, c)
	}

	return chats, nil
}

func (ms *MessageStore) ListGroups(limit, offset int) ([]Chat, error) {
	rows, err := ms.db.Query(`
		SELECT
			c.jid, c.name, c.last_message_time,
			m.content, m.sender, m.is_from_me
		FROM chats c
		LEFT JOIN messages m ON c.jid = m.chat_jid
			AND c.last_message_time = m.timestamp
		WHERE c.jid LIKE '%@g.us'
		ORDER BY c.last_message_time DESC
		LIMIT ? OFFSET ?
	`, limit, offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var groups []Chat
	for rows.Next() {
		var c Chat
		var name, lastMsg, lastSender sql.NullString
		var lastTime sql.NullTime
		var lastIsFromMe sql.NullBool

		if err := rows.Scan(
			&c.JID, &name, &lastTime,
			&lastMsg, &lastSender, &lastIsFromMe,
		); err != nil {
			continue
		}

		c.Name = name.String
		if lastTime.Valid {
			c.LastMessageTime = lastTime.Time
		}
		c.LastMessage = lastMsg.String
		c.LastSender = lastSender.String
		c.LastIsFromMe = lastIsFromMe.Bool
		c.IsGroup = true

		groups = append(groups, c)
	}

	return groups, nil
}

func (ms *MessageStore) GetMessageMediaInfo(messageID, chatJID string) (*MediaInfo, error) {
	var info MediaInfo
	var mediaType, filename, url sql.NullString
	var mediaKey, fileSHA256, fileEncSHA256 []byte
	var fileLength sql.NullInt64

	err := ms.db.QueryRow(`
		SELECT id, chat_jid, media_type, filename, url,
			media_key, file_sha256, file_enc_sha256, file_length
		FROM messages
		WHERE id = ? AND chat_jid = ?
	`, messageID, chatJID).Scan(
		&info.MessageID, &info.ChatJID, &mediaType, &filename, &url,
		&mediaKey, &fileSHA256, &fileEncSHA256, &fileLength,
	)

	if err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("message not found: %s in chat %s", messageID, chatJID)
		}
		return nil, fmt.Errorf("failed to query media info: %v", err)
	}

	info.MediaType = mediaType.String
	info.Filename = filename.String
	info.URL = url.String
	info.MediaKey = mediaKey
	info.FileSHA256 = fileSHA256
	info.FileEncSHA256 = fileEncSHA256
	if fileLength.Valid {
		info.FileLength = uint64(fileLength.Int64)
	}

	if info.MediaType == "" || info.URL == "" {
		return nil, fmt.Errorf("message %s has no media", messageID)
	}

	return &info, nil
}