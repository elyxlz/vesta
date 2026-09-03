package main

import (
	"strings"
	"testing"
)

func newContactTestStore(t *testing.T) *MessageStore {
	t.Helper()
	store, err := NewMessageStore(t.TempDir())
	if err != nil {
		t.Fatalf("failed to open store: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	return store
}

// A saved name must reach one person, so a name another chat already holds is refused.
func TestAddContactRejectsDuplicateNameForADifferentChat(t *testing.T) {
	store := newContactTestStore(t)
	if _, err := store.SaveManualContact("Sarah", 111, ""); err != nil {
		t.Fatalf("failed to save first contact: %v", err)
	}
	_, err := store.SaveManualContact("Sarah", 222, "")
	if err == nil || !strings.Contains(err.Error(), "already exists") {
		t.Fatalf("a duplicate name for a different chat must be refused, got %v", err)
	}
	if !strings.Contains(err.Error(), "111") {
		t.Errorf("the error must name the chat already holding the name, got %v", err)
	}
}

// Case and surrounding spaces must not slip a duplicate past the check.
func TestAddContactRejectsDuplicateNameIgnoringCaseAndSpace(t *testing.T) {
	store := newContactTestStore(t)
	if _, err := store.SaveManualContact("Sarah", 111, ""); err != nil {
		t.Fatalf("failed to save first contact: %v", err)
	}
	if _, err := store.SaveManualContact("  sarah ", 222, ""); err == nil {
		t.Fatalf("a duplicate name differing only by case or space must be refused")
	}
}

// Re-saving or renaming the same chat is an update, never a self-collision.
func TestAddContactAllowsRenamingTheSameChat(t *testing.T) {
	store := newContactTestStore(t)
	if _, err := store.SaveManualContact("Sarah", 111, ""); err != nil {
		t.Fatalf("failed to save contact: %v", err)
	}
	if _, err := store.SaveManualContact("Sarah R", 111, ""); err != nil {
		t.Errorf("renaming the same chat must succeed, got %v", err)
	}
	if _, err := store.SaveManualContact("Sarah", 111, ""); err != nil {
		t.Errorf("re-saving the same chat under its own name must succeed, got %v", err)
	}
}

// A unique saved name still resolves to its chat.
func TestResolveRecipientResolvesAUniqueSavedName(t *testing.T) {
	store := newContactTestStore(t)
	if _, err := store.SaveManualContact("Bob", 333, ""); err != nil {
		t.Fatalf("failed to save contact: %v", err)
	}
	id, err := store.ResolveRecipient("Bob")
	if err != nil {
		t.Fatalf("a unique saved name must resolve, got %v", err)
	}
	if id != 333 {
		t.Errorf("expected chat 333, got %d", id)
	}
}

// Legacy data can already hold two contacts under one name. A name-based send must fail safe with
// the candidates, never silently reach one of them.
func TestResolveRecipientErrorsWhenTwoContactsShareAName(t *testing.T) {
	store := newContactTestStore(t)
	for _, id := range []int64{111, 222} {
		if _, err := store.db.Exec(`INSERT INTO contacts (chat_id, name) VALUES (?, ?)`, id, "Sarah"); err != nil {
			t.Fatalf("failed to seed contact %d: %v", id, err)
		}
	}
	_, err := store.ResolveRecipient("Sarah")
	if err == nil || !strings.Contains(err.Error(), "ambiguous") {
		t.Fatalf("two contacts sharing a name must resolve to an ambiguity error, got %v", err)
	}
	if !strings.Contains(err.Error(), "111") || !strings.Contains(err.Error(), "222") {
		t.Errorf("the ambiguity error must name both chat ids, got %v", err)
	}
}
