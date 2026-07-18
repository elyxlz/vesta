package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func savedCtx(dir string) NotifContext {
	return NotifContext{
		NotifDir: dir, Instance: "personal", ChatName: "Ana",
		ContactName: "Ana", ContactPhone: "+15551234567",
		ContactSaved: true, IsDirectChat: true, Sender: "Ana",
	}
}

func unsavedCtx(dir string) NotifContext {
	return NotifContext{
		NotifDir: dir, Instance: "personal", ChatName: "+15559998888",
		ContactName: "", ContactPhone: "+15559998888",
		ContactSaved: false, IsDirectChat: true, Sender: "+15559998888",
	}
}

// soleNotifFields decodes the one notification in dir as a field map, so a test can assert
// that a key is absent rather than merely empty.
func soleNotifFields(t *testing.T, dir string) map[string]json.RawMessage {
	t.Helper()
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("failed to read notifications dir: %v", err)
	}
	if len(entries) != 1 {
		t.Fatalf("expected exactly one notification, got %d", len(entries))
	}
	raw, err := os.ReadFile(filepath.Join(dir, entries[0].Name()))
	if err != nil {
		t.Fatalf("failed to read notification: %v", err)
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		t.Fatalf("notification is not valid json: %v", err)
	}
	return fields
}

func TestSavedContactIsNamedWithoutRestatingTheirNumber(t *testing.T) {
	dir := t.TempDir()

	if err := WriteNotification(savedCtx(dir), "3EB0A1", "are you coming", "", false, "", ""); err != nil {
		t.Fatalf("write failed: %v", err)
	}

	fields := soleNotifFields(t, dir)
	if _, present := fields["contact_phone"]; present {
		t.Errorf("contact_phone is present for a saved contact; the name is what `send --to` takes")
	}
	var name string
	if err := json.Unmarshal(fields["contact_name"], &name); err != nil || name != "Ana" {
		t.Errorf("contact_name = %q, want Ana (the saved contact must still be named)", name)
	}
}

func TestUnsavedContactIsIdentifiedByNumber(t *testing.T) {
	dir := t.TempDir()

	if err := WriteNotification(unsavedCtx(dir), "3EB0A1", "hello", "", false, "", ""); err != nil {
		t.Fatalf("write failed: %v", err)
	}

	fields := soleNotifFields(t, dir)
	var phone string
	if err := json.Unmarshal(fields["contact_phone"], &phone); err != nil || phone != "+15559998888" {
		t.Errorf("contact_phone = %q, want the number: it is the only way to reply to someone unsaved", phone)
	}
	if _, present := fields["contact_name"]; present {
		t.Errorf("contact_name is present for an unsaved contact, want it absent")
	}
	if _, present := fields["contact_unknown"]; !present {
		t.Errorf("contact_unknown is absent for an unsaved contact, want it flagged")
	}
}

func TestSavedContactReactionAlsoOmitsTheNumber(t *testing.T) {
	dir := t.TempDir()

	if err := WriteReactionNotification(savedCtx(dir), "3EB0A1", "❤️", false); err != nil {
		t.Fatalf("write failed: %v", err)
	}

	if _, present := soleNotifFields(t, dir)["contact_phone"]; present {
		t.Errorf("contact_phone is present on a saved contact's reaction, want it omitted")
	}
}

func TestUnsavedContactReactionKeepsTheNumber(t *testing.T) {
	dir := t.TempDir()

	if err := WriteReactionNotification(unsavedCtx(dir), "3EB0A1", "❤️", false); err != nil {
		t.Fatalf("write failed: %v", err)
	}

	fields := soleNotifFields(t, dir)
	var phone string
	if err := json.Unmarshal(fields["contact_phone"], &phone); err != nil || phone != "+15559998888" {
		t.Errorf("contact_phone = %q, want the number for an unsaved reactor", phone)
	}
}

// The primary account runs without --instance, so it never labels its notifications; a second
// named account is the only thing that does.
func TestPrimaryAccountDoesNotLabelItsInstance(t *testing.T) {
	dir := t.TempDir()
	ctx := savedCtx(dir)
	ctx.Instance = ""

	if err := WriteNotification(ctx, "3EB0A1", "are you coming", "", false, "", ""); err != nil {
		t.Fatalf("write failed: %v", err)
	}

	if _, present := soleNotifFields(t, dir)["instance"]; present {
		t.Errorf("instance is present for the unnamed primary account, want it omitted")
	}
}
