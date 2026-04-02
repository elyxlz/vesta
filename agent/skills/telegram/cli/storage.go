package main

import (
	"database/sql"
	"fmt"
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

	db, err := sql.Open("sqlite3", dbPath+"?_foreign_keys=on")
	if err != nil {
		return nil, fmt.Errorf("failed to open message database: %v", err)
	}

	_, err = db.Exec(`
		CREATE TABLE IF NOT EXISTS chats (
			id INTEGER PRIMARY KEY,
			name TEXT,
			chat_type TEXT DEFAULT 'private',
			last_message_time TIMESTAMP
		);

		CREATE TABLE IF NOT EXISTS messages (
			id INTEGER PRIMARY KEY,
			chat_id INTEGER,
			sender TEXT,
			content TEXT,
			timestamp TIMESTAMP,
			is_from_me BOOLEAN,
			media_type TEXT,
			filename TEXT,
			file_id TEXT,
			reply_to_id INTEGER,
			FOREIGN KEY (chat_id) REFERENCES chats(id)
		);

		CREATE TABLE IF NOT EXISTS contacts (
			chat_id INTEGER PRIMARY KEY,
			name TEXT,
			username TEXT,
			added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		);

		CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
		CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender);
		CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id);
		CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(name);
		CREATE INDEX IF NOT EXISTS idx_contacts_username ON contacts(username);
	`)
	if err != nil {
		db.Close()
		return nil, fmt.Errorf("failed to create tables: %v", err)
	}

	_, err = db.Exec(`
		CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
			content, chat_name, sender
		);

		CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
			INSERT INTO messages_fts(rowid, content, chat_name, sender)
			VALUES (new.rowid, new.content,
				(SELECT name FROM chats WHERE id = new.chat_id),
				new.sender);
		END;

		CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
			DELETE FROM messages_fts WHERE rowid = old.rowid;
		END;

		CREATE TRIGGER IF NOT EXISTS chats_au AFTER UPDATE OF name ON chats BEGIN
			DELETE FROM messages_fts WHERE rowid IN (
				SELECT rowid FROM messages WHERE chat_id = new.id
			);
			INSERT INTO messages_fts(rowid, content, chat_name, sender)
			SELECT m.rowid, m.content, new.name, m.sender
			FROM messages m WHERE m.chat_id = new.id;
		END;
	`)
	if err != nil {
		db.Close()
		return nil, fmt.Errorf("failed to create FTS index: %v", err)
	}

	ms := &MessageStore{db: db}
	if err := ms.rebuildFTS(); err != nil {
		db.Close()
		return nil, err
	}
	return ms, nil
}

func (ms *MessageStore) Close() error {
	return ms.db.Close()
}

func (ms *MessageStore) rebuildFTS() error {
	var count int
	if err := ms.db.QueryRow("SELECT COUNT(*) FROM messages_fts").Scan(&count); err != nil {
		return fmt.Errorf("failed to check FTS index: %v", err)
	}
	if count > 0 {
		return nil
	}
	var msgCount int
	if err := ms.db.QueryRow("SELECT COUNT(*) FROM messages").Scan(&msgCount); err != nil {
		return fmt.Errorf("failed to count messages: %v", err)
	}
	if msgCount == 0 {
		return nil
	}
	_, err := ms.db.Exec(`
		INSERT INTO messages_fts(rowid, content, chat_name, sender)
		SELECT m.rowid, m.content,
			(SELECT name FROM chats WHERE id = m.chat_id),
			m.sender
		FROM messages m
		WHERE m.content IS NOT NULL AND m.content != ''
	`)
	if err != nil {
		return fmt.Errorf("failed to rebuild FTS index: %v", err)
	}
	return nil
}

func (ms *MessageStore) StoreChat(chatID int64, name, chatType string, lastMessageTime time.Time) error {
	_, err := ms.db.Exec(`
		INSERT INTO chats (id, name, chat_type, last_message_time)
		VALUES (?, ?, ?, ?)
		ON CONFLICT(id) DO UPDATE SET
			name = COALESCE(excluded.name, chats.name),
			chat_type = COALESCE(excluded.chat_type, chats.chat_type),
			last_message_time = CASE
				WHEN excluded.last_message_time > chats.last_message_time
				THEN excluded.last_message_time
				ELSE chats.last_message_time
			END
	`, chatID, name, chatType, lastMessageTime)
	return err
}

func (ms *MessageStore) StoreMessage(
	msgID, chatID int64, sender, content string,
	timestamp time.Time, isFromMe bool,
	mediaType, filename, fileID string,
	replyToID int64,
) error {
	_, err := ms.db.Exec(`
		INSERT OR REPLACE INTO messages (
			id, chat_id, sender, content, timestamp,
			is_from_me, media_type, filename, file_id, reply_to_id
		) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
	`, msgID, chatID, sender, content, timestamp, isFromMe,
		mediaType, filename, fileID, replyToID)
	return err
}

func (ms *MessageStore) GetChatName(chatID int64) (string, error) {
	var name sql.NullString
	err := ms.db.QueryRow("SELECT name FROM chats WHERE id = ?", chatID).Scan(&name)
	if err != nil {
		return "", err
	}
	return name.String, nil
}

func (ms *MessageStore) SearchContacts(query string, limit int) ([]Contact, error) {
	if limit <= 0 {
		limit = 50
	}

	contacts := make([]Contact, 0, limit)
	seen := make(map[int64]struct{})
	lowerQuery := strings.ToLower(query)
	likeName := "%" + lowerQuery + "%"

	// Manual contacts first
	rows, err := ms.db.Query(`
		SELECT chat_id, name, username
		FROM contacts
		WHERE LOWER(COALESCE(name, '')) LIKE ? OR LOWER(COALESCE(username, '')) LIKE ?
		ORDER BY LOWER(COALESCE(name, username))
		LIMIT ?
	`, likeName, likeName, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	for rows.Next() {
		if len(contacts) >= limit {
			break
		}
		var c Contact
		var name, username sql.NullString
		if err := rows.Scan(&c.ChatID, &name, &username); err != nil {
			continue
		}
		c.Name = name.String
		c.Username = username.String
		c.IsManual = true
		contacts = append(contacts, c)
		seen[c.ChatID] = struct{}{}
	}

	if len(contacts) >= limit {
		return contacts, nil
	}

	// Then chats
	remaining := limit - len(contacts)
	chatRows, err := ms.db.Query(`
		SELECT id, name, chat_type
		FROM chats
		WHERE chat_type = 'private'
		AND LOWER(COALESCE(name, '')) LIKE ?
		ORDER BY LOWER(COALESCE(name, ''))
		LIMIT ?
	`, likeName, remaining*2)
	if err != nil {
		return contacts, err
	}
	defer chatRows.Close()

	for chatRows.Next() {
		if len(contacts) >= limit {
			break
		}
		var chatID int64
		var name sql.NullString
		var chatType string
		if err := chatRows.Scan(&chatID, &name, &chatType); err != nil {
			continue
		}
		if _, exists := seen[chatID]; exists {
			continue
		}
		contacts = append(contacts, Contact{
			ChatID: chatID,
			Name:   name.String,
		})
		seen[chatID] = struct{}{}
	}

	return contacts, nil
}

func (ms *MessageStore) SaveManualContact(name string, chatID int64, username string) (Contact, error) {
	trimmedName := strings.TrimSpace(name)
	if trimmedName == "" {
		return Contact{}, fmt.Errorf("contact name cannot be empty")
	}
	_, err := ms.db.Exec(`
		INSERT INTO contacts (chat_id, name, username, added_at, updated_at)
		VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
		ON CONFLICT(chat_id) DO UPDATE SET
			name = excluded.name,
			username = excluded.username,
			updated_at = CURRENT_TIMESTAMP
	`, chatID, trimmedName, username)
	if err != nil {
		return Contact{}, fmt.Errorf("failed to save contact: %v", err)
	}
	return Contact{
		ChatID:   chatID,
		Name:     trimmedName,
		Username: username,
		IsManual: true,
	}, nil
}

func (ms *MessageStore) GetManualContact(chatID int64) (*Contact, error) {
	var name, username sql.NullString
	err := ms.db.QueryRow(`
		SELECT name, username FROM contacts WHERE chat_id = ?
	`, chatID).Scan(&name, &username)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &Contact{
		ChatID:   chatID,
		Name:     name.String,
		Username: username.String,
		IsManual: true,
	}, nil
}

func (ms *MessageStore) DeleteManualContact(identifier string) error {
	result, err := ms.db.Exec(`DELETE FROM contacts WHERE name = ?`, identifier)
	if err != nil {
		return err
	}
	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("failed to check delete result: %v", err)
	}
	if rows > 0 {
		return nil
	}

	// Try by username
	result, err = ms.db.Exec(`DELETE FROM contacts WHERE username = ?`, strings.TrimPrefix(identifier, "@"))
	if err != nil {
		return err
	}
	rows, err = result.RowsAffected()
	if err != nil {
		return fmt.Errorf("failed to check delete result: %v", err)
	}
	if rows > 0 {
		return nil
	}

	return fmt.Errorf("contact not found: %s", identifier)
}

func (ms *MessageStore) ListMessages(
	after, before *time.Time,
	sender string, chatID int64, query string,
	limit, offset int,
) ([]Message, error) {
	if query != "" {
		messages, err := ms.listMessagesFTS(after, before, sender, chatID, query, limit, offset)
		if err == nil {
			return messages, nil
		}
	}
	return ms.listMessagesLike(after, before, sender, chatID, query, limit, offset)
}

func (ms *MessageStore) listMessagesFTS(
	after, before *time.Time,
	sender string, chatID int64, query string,
	limit, offset int,
) ([]Message, error) {
	qb := strings.Builder{}
	qb.WriteString(`
		SELECT
			m.id, m.chat_id, c.name, m.sender, m.content,
			m.timestamp, m.is_from_me, m.media_type, m.filename, m.reply_to_id
		FROM messages m
		JOIN chats c ON m.chat_id = c.id
		JOIN messages_fts ON messages_fts.rowid = m.rowid
		WHERE messages_fts MATCH ?
	`)
	args := []interface{}{query}

	if after != nil {
		qb.WriteString(" AND m.timestamp >= ?")
		args = append(args, *after)
	}
	if before != nil {
		qb.WriteString(" AND m.timestamp <= ?")
		args = append(args, *before)
	}
	if sender != "" {
		qb.WriteString(" AND m.sender LIKE ?")
		args = append(args, "%"+sender+"%")
	}
	if chatID != 0 {
		qb.WriteString(" AND m.chat_id = ?")
		args = append(args, chatID)
	}

	qb.WriteString(" ORDER BY m.timestamp DESC LIMIT ? OFFSET ?")
	args = append(args, limit, offset)

	return ms.scanMessages(ms.db.Query(qb.String(), args...))
}

func (ms *MessageStore) listMessagesLike(
	after, before *time.Time,
	sender string, chatID int64, query string,
	limit, offset int,
) ([]Message, error) {
	qb := strings.Builder{}
	qb.WriteString(`
		SELECT
			m.id, m.chat_id, c.name, m.sender, m.content,
			m.timestamp, m.is_from_me, m.media_type, m.filename, m.reply_to_id
		FROM messages m
		JOIN chats c ON m.chat_id = c.id
		WHERE 1=1
	`)
	args := []interface{}{}

	if after != nil {
		qb.WriteString(" AND m.timestamp >= ?")
		args = append(args, *after)
	}
	if before != nil {
		qb.WriteString(" AND m.timestamp <= ?")
		args = append(args, *before)
	}
	if sender != "" {
		qb.WriteString(" AND m.sender LIKE ?")
		args = append(args, "%"+sender+"%")
	}
	if chatID != 0 {
		qb.WriteString(" AND m.chat_id = ?")
		args = append(args, chatID)
	}
	if query != "" {
		qb.WriteString(" AND m.content LIKE ?")
		args = append(args, "%"+query+"%")
	}

	qb.WriteString(" ORDER BY m.timestamp DESC LIMIT ? OFFSET ?")
	args = append(args, limit, offset)

	return ms.scanMessages(ms.db.Query(qb.String(), args...))
}

func (ms *MessageStore) scanMessages(rows *sql.Rows, err error) ([]Message, error) {
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var messages []Message
	for rows.Next() {
		var m Message
		var chatName, mediaType, filename sql.NullString
		var replyToID sql.NullInt64
		if err := rows.Scan(
			&m.ID, &m.ChatID, &chatName, &m.Sender, &m.Content,
			&m.Timestamp, &m.IsFromMe, &mediaType, &filename, &replyToID,
		); err != nil {
			continue
		}
		m.ChatName = chatName.String
		m.MediaType = mediaType.String
		m.Filename = filename.String
		if replyToID.Valid {
			m.ReplyToID = replyToID.Int64
		}
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
	qb := strings.Builder{}

	if includeLastMessage {
		qb.WriteString(`
			SELECT
				c.id, c.name, c.chat_type, c.last_message_time,
				m.content, m.sender, m.is_from_me
			FROM chats c
			LEFT JOIN messages m ON c.id = m.chat_id
				AND c.last_message_time = m.timestamp
		`)
	} else {
		qb.WriteString(`
			SELECT
				c.id, c.name, c.chat_type, c.last_message_time,
				NULL, NULL, NULL
			FROM chats c
		`)
	}

	args := []interface{}{}
	if query != "" {
		qb.WriteString(" WHERE c.name LIKE ?")
		args = append(args, "%"+query+"%")
	}

	if sortBy == "name" {
		qb.WriteString(" ORDER BY c.name")
	} else {
		qb.WriteString(" ORDER BY c.last_message_time DESC")
	}

	qb.WriteString(" LIMIT ? OFFSET ?")
	args = append(args, limit, offset)

	rows, err := ms.db.Query(qb.String(), args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var chats []Chat
	for rows.Next() {
		var c Chat
		var name, lastMsg, lastSender sql.NullString
		var chatType sql.NullString
		var lastTime sql.NullTime
		var lastIsFromMe sql.NullBool

		if err := rows.Scan(
			&c.ID, &name, &chatType, &lastTime,
			&lastMsg, &lastSender, &lastIsFromMe,
		); err != nil {
			continue
		}

		c.Name = name.String
		c.ChatType = chatType.String
		if lastTime.Valid {
			c.LastMessageTime = lastTime.Time
		}
		c.LastMessage = lastMsg.String
		c.LastSender = lastSender.String
		c.LastIsFromMe = lastIsFromMe.Bool

		chats = append(chats, c)
	}

	return chats, nil
}

func (ms *MessageStore) ListGroups(limit, offset int) ([]Chat, error) {
	rows, err := ms.db.Query(`
		SELECT
			c.id, c.name, c.chat_type, c.last_message_time,
			m.content, m.sender, m.is_from_me
		FROM chats c
		LEFT JOIN messages m ON c.id = m.chat_id
			AND c.last_message_time = m.timestamp
		WHERE c.chat_type IN ('group', 'supergroup')
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
		var chatType sql.NullString
		var lastTime sql.NullTime
		var lastIsFromMe sql.NullBool

		if err := rows.Scan(
			&c.ID, &name, &chatType, &lastTime,
			&lastMsg, &lastSender, &lastIsFromMe,
		); err != nil {
			continue
		}

		c.Name = name.String
		c.ChatType = chatType.String
		if lastTime.Valid {
			c.LastMessageTime = lastTime.Time
		}
		c.LastMessage = lastMsg.String
		c.LastSender = lastSender.String
		c.LastIsFromMe = lastIsFromMe.Bool

		groups = append(groups, c)
	}

	return groups, nil
}

// ResolveRecipient resolves a contact identifier to a chat ID.
// Accepts: numeric chat ID, @username, or contact name.
func (ms *MessageStore) ResolveRecipient(identifier string) (int64, error) {
	identifier = strings.TrimSpace(identifier)

	// Try as numeric chat ID
	if chatID, err := parseInt64(identifier); err == nil {
		return chatID, nil
	}

	// Try as @username
	username := strings.TrimPrefix(identifier, "@")
	var chatID int64
	err := ms.db.QueryRow(`SELECT chat_id FROM contacts WHERE LOWER(username) = LOWER(?)`, username).Scan(&chatID)
	if err == nil {
		return chatID, nil
	}

	// Try as contact name (exact match first)
	err = ms.db.QueryRow(`SELECT chat_id FROM contacts WHERE LOWER(name) = LOWER(?)`, identifier).Scan(&chatID)
	if err == nil {
		return chatID, nil
	}

	// Try as chat name
	err = ms.db.QueryRow(`SELECT id FROM chats WHERE LOWER(name) = LOWER(?)`, identifier).Scan(&chatID)
	if err == nil {
		return chatID, nil
	}

	// Fuzzy match on contact name
	var matches []struct {
		chatID int64
		name   string
	}
	rows, err := ms.db.Query(`
		SELECT chat_id, name FROM contacts
		WHERE LOWER(name) LIKE LOWER(?)
		LIMIT 5
	`, "%"+identifier+"%")
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var m struct {
				chatID int64
				name   string
			}
			if rows.Scan(&m.chatID, &m.name) == nil {
				matches = append(matches, m)
			}
		}
	}

	if len(matches) == 1 {
		return matches[0].chatID, nil
	}
	if len(matches) > 1 {
		var names []string
		for _, m := range matches {
			names = append(names, m.name)
		}
		return 0, fmt.Errorf("ambiguous recipient %q — matches: %s", identifier, strings.Join(names, ", "))
	}

	return 0, fmt.Errorf("recipient not found: %s. Add them as a contact first with: telegram add-contact <name> <chat-id>", identifier)
}

func parseInt64(s string) (int64, error) {
	var n int64
	for _, c := range s {
		if c == '-' && n == 0 {
			continue
		}
		if c < '0' || c > '9' {
			return 0, fmt.Errorf("not a number")
		}
		n = n*10 + int64(c-'0')
	}
	if len(s) > 0 && s[0] == '-' {
		n = -n
	}
	return n, nil
}
