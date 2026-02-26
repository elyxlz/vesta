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
	"go.mau.fi/whatsmeow/types"
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

		CREATE TABLE IF NOT EXISTS contacts (
			jid TEXT PRIMARY KEY,
			phone_number TEXT NOT NULL,
			name TEXT,
			added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		);

		CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
		CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender);
		CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_jid);
		CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(phone_number);
		CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(name);

		CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
			content, chat_name, sender,
			content='messages', content_rowid='rowid'
		);

		CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
			INSERT INTO messages_fts(rowid, content, chat_name, sender)
			VALUES (new.rowid, new.content,
				(SELECT name FROM chats WHERE jid = new.chat_jid),
				new.sender);
		END;

		CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
			INSERT INTO messages_fts(messages_fts, rowid, content, chat_name, sender)
			VALUES('delete', old.rowid, old.content,
				(SELECT name FROM chats WHERE jid = old.chat_jid),
				old.sender);
		END;
	`)
	if err != nil {
		db.Close()
		return nil, fmt.Errorf("failed to create tables: %v", err)
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
			(SELECT name FROM chats WHERE jid = m.chat_jid),
			m.sender
		FROM messages m
		WHERE m.content IS NOT NULL AND m.content != ''
	`)
	if err != nil {
		return fmt.Errorf("failed to rebuild FTS index: %v", err)
	}
	return nil
}

func (ms *MessageStore) GetOldestMessage(chatJID string) (string, string, bool, time.Time, error) {
	var id, sender string
	var isFromMe bool
	var ts time.Time
	err := ms.db.QueryRow(`
		SELECT id, sender, is_from_me, timestamp
		FROM messages WHERE chat_jid = ?
		ORDER BY timestamp ASC LIMIT 1
	`, chatJID).Scan(&id, &sender, &isFromMe, &ts)
	if err != nil {
		return "", "", false, time.Time{}, err
	}
	return id, sender, isFromMe, ts, nil
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
	if limit <= 0 {
		limit = 50
	}

	contacts := make([]Contact, 0, limit)
	seen := make(map[string]struct{})

	lowerQuery := strings.ToLower(query)
	likeName := "%" + lowerQuery + "%"
	jidLike := "%" + lowerQuery + "%"
	rawDigits := digitsOnly(query)
	digitsLike := "%"
	if rawDigits != "" {
		digitsLike = "%" + rawDigits + "%"
	}

	manualConditions := []string{
		"LOWER(COALESCE(name, '')) LIKE ?",
		"phone_number LIKE ?",
		"LOWER(jid) LIKE ?",
	}
	manualArgs := []interface{}{likeName, jidLike, jidLike}
	if rawDigits != "" {
		manualConditions = append(manualConditions, "REPLACE(phone_number, '+', '') LIKE ?")
		manualArgs = append(manualArgs, digitsLike)
	}
	manualQuery := fmt.Sprintf(`
		SELECT jid, name, phone_number
		FROM contacts
		WHERE (%s)
		ORDER BY LOWER(COALESCE(name, phone_number))
		LIMIT ?
	`, strings.Join(manualConditions, " OR "))
	manualArgs = append(manualArgs, limit)

	manualRows, err := ms.db.Query(manualQuery, manualArgs...)
	if err != nil {
		return nil, err
	}
	defer manualRows.Close()

	for manualRows.Next() {
		if len(contacts) >= limit {
			break
		}
		var c Contact
		var name sql.NullString
		if err := manualRows.Scan(&c.JID, &name, &c.PhoneNumber); err != nil {
			continue
		}
		c.Name = name.String
		c.IsManual = true
		contacts = append(contacts, c)
		seen[c.JID] = struct{}{}
	}

	if len(contacts) >= limit {
		return contacts, nil
	}

	remaining := limit - len(contacts)
	chatConditions := []string{
		"LOWER(COALESCE(name, '')) LIKE ?",
		"LOWER(jid) LIKE ?",
	}
	chatArgs := []interface{}{likeName, jidLike}
	if rawDigits != "" {
		chatConditions = append(chatConditions, "SUBSTR(jid, 1, INSTR(jid, '@') - 1) LIKE ?")
		chatArgs = append(chatArgs, digitsLike)
	}
	chatQuery := fmt.Sprintf(`
		SELECT jid, name
		FROM chats
		WHERE jid LIKE '%%@s.whatsapp.net'
		AND (%s)
		ORDER BY LOWER(COALESCE(name, jid))
		LIMIT ?
	`, strings.Join(chatConditions, " OR "))
	chatArgs = append(chatArgs, remaining*2)

	chatRows, err := ms.db.Query(chatQuery, chatArgs...)
	if err != nil {
		return contacts, err
	}
	defer chatRows.Close()

	for chatRows.Next() {
		if len(contacts) >= limit {
			break
		}
		var jid string
		var name sql.NullString
		if err := chatRows.Scan(&jid, &name); err != nil {
			continue
		}
		if _, exists := seen[jid]; exists {
			continue
		}
		c := Contact{
			JID:         jid,
			Name:        name.String,
			PhoneNumber: jidToPhone(jid),
		}
		contacts = append(contacts, c)
		seen[jid] = struct{}{}
	}

	return contacts, nil
}

func (ms *MessageStore) SaveManualContact(name, phone string) (Contact, error) {
	normalizedDigits, displayNumber, err := normalizePhoneInput(phone)
	trimmedName := strings.TrimSpace(name)
	if err != nil {
		return Contact{}, err
	}
	if trimmedName == "" {
		return Contact{}, fmt.Errorf("contact name cannot be empty")
	}
	jid := fmt.Sprintf("%s@%s", normalizedDigits, types.DefaultUserServer)
	_, err = ms.db.Exec(`
		INSERT INTO contacts (jid, phone_number, name, added_at, updated_at)
		VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
		ON CONFLICT(jid) DO UPDATE SET
			name = excluded.name,
			phone_number = excluded.phone_number,
			updated_at = CURRENT_TIMESTAMP
	`, jid, displayNumber, trimmedName)
	if err != nil {
		return Contact{}, fmt.Errorf("failed to save contact: %v", err)
	}

	return Contact{
		JID:         jid,
		Name:        trimmedName,
		PhoneNumber: displayNumber,
		IsManual:    true,
	}, nil
}

func (ms *MessageStore) GetManualContact(jid string) (*Contact, error) {
	var name sql.NullString
	var phone string
	err := ms.db.QueryRow(`
		SELECT name, phone_number
		FROM contacts
		WHERE jid = ?
	`, jid).Scan(&name, &phone)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}

	return &Contact{
		JID:         jid,
		Name:        name.String,
		PhoneNumber: phone,
		IsManual:    true,
	}, nil
}

func (ms *MessageStore) DeleteManualContact(identifier string) error {
	// Try by name first
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

	// Try by phone number
	normalized, _, err := normalizePhoneInput(identifier)
	if err == nil {
		jid := fmt.Sprintf("%s@%s", normalized, types.DefaultUserServer)
		result, err = ms.db.Exec(`DELETE FROM contacts WHERE jid = ?`, jid)
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
	}

	return fmt.Errorf("contact not found: %s", identifier)
}

func digitsOnly(input string) string {
	var b strings.Builder
	for _, r := range input {
		if r >= '0' && r <= '9' {
			b.WriteRune(r)
		}
	}
	return b.String()
}

func jidToPhone(jid string) string {
	if idx := strings.Index(jid, "@"); idx > 0 {
		digits := digitsOnly(jid[:idx])
		if digits != "" {
			return "+" + digits
		}
		return digits
	}
	return ""
}

func normalizePhoneInput(input string) (string, string, error) {
	clean := strings.TrimSpace(input)
	if clean == "" {
		return "", "", fmt.Errorf("phone number cannot be empty")
	}
	if at := strings.Index(clean, "@"); at > 0 {
		clean = clean[:at]
	}
	clean = strings.TrimPrefix(clean, "+")
	digits := digitsOnly(clean)
	if digits == "" {
		return "", "", fmt.Errorf("phone number must contain digits")
	}
	return digits, "+" + digits, nil
}

func (ms *MessageStore) ListMessages(
	after, before *time.Time,
	senderPhone, chatJID, query string,
	limit, offset int,
) ([]Message, error) {
	if query != "" {
		messages, err := ms.listMessagesFTS(after, before, senderPhone, chatJID, query, limit, offset)
		if err == nil {
			return messages, nil
		}
	}

	return ms.listMessagesLike(after, before, senderPhone, chatJID, query, limit, offset)
}

func (ms *MessageStore) listMessagesFTS(
	after, before *time.Time,
	senderPhone, chatJID, query string,
	limit, offset int,
) ([]Message, error) {
	qb := strings.Builder{}
	qb.WriteString(`
		SELECT
			m.id, m.chat_jid, c.name, m.sender, m.content,
			m.timestamp, m.is_from_me, m.is_forwarded, m.media_type, m.filename
		FROM messages m
		JOIN chats c ON m.chat_jid = c.jid
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
	if senderPhone != "" {
		qb.WriteString(" AND m.sender LIKE ?")
		args = append(args, "%"+senderPhone+"%")
	}
	if chatJID != "" {
		qb.WriteString(" AND m.chat_jid = ?")
		args = append(args, chatJID)
	}

	qb.WriteString(" ORDER BY m.timestamp DESC LIMIT ? OFFSET ?")
	args = append(args, limit, offset)

	return ms.scanMessages(ms.db.Query(qb.String(), args...))
}

func (ms *MessageStore) listMessagesLike(
	after, before *time.Time,
	senderPhone, chatJID, query string,
	limit, offset int,
) ([]Message, error) {
	qb := strings.Builder{}
	qb.WriteString(`
		SELECT
			m.id, m.chat_jid, c.name, m.sender, m.content,
			m.timestamp, m.is_from_me, m.is_forwarded, m.media_type, m.filename
		FROM messages m
		JOIN chats c ON m.chat_jid = c.jid
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
	if senderPhone != "" {
		qb.WriteString(" AND m.sender LIKE ?")
		args = append(args, "%"+senderPhone+"%")
	}
	if chatJID != "" {
		qb.WriteString(" AND m.chat_jid = ?")
		args = append(args, chatJID)
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
			return nil, fmt.Errorf("message %s not found in this chat", messageID)
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
