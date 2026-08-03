package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func savedCtx(dir string) NotifContext {
	return NotifContext{
		NotifDir: dir, Instance: "personal", ChatJID: "4477000111@s.whatsapp.net", ChatName: "Ana",
		ContactName: "Ana", ContactPhone: "+15551234567",
		ContactSaved: true, IsDirectChat: true, Sender: "Ana",
	}
}

func unsavedCtx(dir string) NotifContext {
	return NotifContext{
		NotifDir: dir, Instance: "personal", ChatJID: "15559998888@s.whatsapp.net", ChatName: "+15559998888",
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

func prepareAuthNotificationTest(t *testing.T) string {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("DOUBLETICK_API_URL", "")
	t.Setenv("DOUBLETICK_API_KEY", "")
	t.Setenv("WHATSAPP_API_URL", "")
	t.Setenv("WHATSAPP_API_KEY", "")
	t.Setenv("VESTA_CLOUD_CONTROL_URL", "")
	if err := os.MkdirAll(filepath.Join(home, ".whatsapp"), 0700); err != nil {
		t.Fatal(err)
	}
	return t.TempDir()
}

func TestFreshManagedUnpairedCanConnectWithoutApproval(t *testing.T) {
	dir := prepareAuthNotificationTest(t)
	t.Setenv("DOUBLETICK_API_URL", "https://doubletick.example")
	t.Setenv("DOUBLETICK_API_KEY", "wak_secret")

	if err := WriteUnpairedNotification(dir, ""); err != nil {
		t.Fatal(err)
	}
	fields := soleNotifFields(t, dir)
	if _, present := fields["requires_user_approval"]; present {
		t.Fatal("first-time setup must not be mislabeled as a recovery requiring fresh approval")
	}
	var recovery, command string
	_ = json.Unmarshal(fields["recovery"], &recovery)
	_ = json.Unmarshal(fields["next_command"], &command)
	if recovery != "first_link" || command != "whatsapp connect --source doubletick" {
		t.Fatalf("fresh managed notification = recovery %q command %q", recovery, command)
	}
}

func TestPreviouslyLinkedUnpairedRequiresApproval(t *testing.T) {
	dir := prepareAuthNotificationTest(t)
	t.Setenv("DOUBLETICK_API_URL", "https://doubletick.example")
	t.Setenv("DOUBLETICK_API_KEY", "wak_secret")
	newStateStore(stateDataDir()).update(func(state *daemonState) { state.LinkedAt = time.Now() })

	if err := WriteUnpairedNotification(dir, ""); err != nil {
		t.Fatal(err)
	}
	fields := soleNotifFields(t, dir)
	var approval bool
	var recovery, message string
	_ = json.Unmarshal(fields["requires_user_approval"], &approval)
	_ = json.Unmarshal(fields["recovery"], &recovery)
	_ = json.Unmarshal(fields["message"], &message)
	if !approval || recovery != "relink" || !strings.Contains(message, "explicit approval") {
		t.Fatalf("lost-link notification did not preserve the approval gate: approval=%v recovery=%q message=%q", approval, recovery, message)
	}
}

func TestLoggedOutNotificationNamesExactApprovedRecoveryCommand(t *testing.T) {
	dir := prepareAuthNotificationTest(t)

	if err := WriteLoggedOutNotification(dir, "personal", "removed"); err != nil {
		t.Fatal(err)
	}
	fields := soleNotifFields(t, dir)
	var approval bool
	var command string
	_ = json.Unmarshal(fields["requires_user_approval"], &approval)
	_ = json.Unmarshal(fields["next_command"], &command)
	if !approval || command != "whatsapp connect --source self-managed --instance 'personal'" {
		t.Fatalf("logged-out recovery = approval %v command %q", approval, command)
	}
}
