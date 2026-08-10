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
		ContactSaved: true, IsDirectChat: true,
	}
}

func unsavedCtx(dir string) NotifContext {
	return NotifContext{
		NotifDir: dir, Instance: "personal", ChatJID: "15559998888@s.whatsapp.net", ChatName: "+15559998888",
		ContactName: "+15559998888", ContactPhone: "+15559998888",
		ContactSaved: false, IsDirectChat: true,
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
	var name string
	if err := json.Unmarshal(fields["contact_name"], &name); err != nil || name != "+15559998888" {
		t.Errorf("contact_name = %q, want the number: the single identity field names an unsaved contact too", name)
	}
	if _, present := fields["contact_unknown"]; !present {
		t.Errorf("contact_unknown is absent for an unsaved contact, want it flagged")
	}
}

func groupCtx(dir string) NotifContext {
	ctx := savedCtx(dir)
	ctx.IsDirectChat = false
	ctx.ChatJID = "120363021234567890@g.us"
	ctx.ChatName = "Bride squad"
	return ctx
}

// unsavedGroupCtx is a group message from someone the user has not saved: the identity is the
// formatted number, and there is no separate group vs participant name to reconcile.
func unsavedGroupCtx(dir string) NotifContext {
	ctx := groupCtx(dir)
	ctx.ContactName = "+15559998888"
	ctx.ContactPhone = "+15559998888"
	ctx.ContactSaved = false
	return ctx
}

// Identity rides in contact_name alone. A group notification used to carry a second `sender`
// field that repeated the participant, so pin that no notification, direct or group, saved or
// unsaved, ever emits one.
func TestNotificationsCarryNoSeparateSenderField(t *testing.T) {
	for _, tc := range []struct {
		name string
		ctx  func(string) NotifContext
	}{
		{"direct-saved", savedCtx},
		{"direct-unsaved", unsavedCtx},
		{"group-saved", groupCtx},
		{"group-unsaved", unsavedGroupCtx},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			if err := WriteNotification(tc.ctx(dir), "3EB0A1", "hi", "", false, "", ""); err != nil {
				t.Fatalf("write failed: %v", err)
			}
			if _, present := soleNotifFields(t, dir)["sender"]; present {
				t.Errorf("notification carries a separate sender field; identity must ride in contact_name alone")
			}
		})
	}
}

// contact_name is the single identity field. It is set for every message, direct or group, and
// carries the saved name when the contact is saved and the formatted number otherwise.
func TestContactNameCarriesTheIdentityForEveryMessage(t *testing.T) {
	for _, tc := range []struct {
		name string
		ctx  func(string) NotifContext
		want string
	}{
		{"direct-saved", savedCtx, "Ana"},
		{"direct-unsaved", unsavedCtx, "+15559998888"},
		{"group-saved", groupCtx, "Ana"},
		{"group-unsaved", unsavedGroupCtx, "+15559998888"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			if err := WriteNotification(tc.ctx(dir), "3EB0A1", "hi", "", false, "", ""); err != nil {
				t.Fatalf("write failed: %v", err)
			}
			var name string
			if err := json.Unmarshal(soleNotifFields(t, dir)["contact_name"], &name); err != nil || name != tc.want {
				t.Errorf("contact_name = %q, want %q (the single identity field)", name, tc.want)
			}
		})
	}
}

func notifChatType(t *testing.T, dir string) string {
	t.Helper()
	var chatType string
	if err := json.Unmarshal(soleNotifFields(t, dir)["chat_type"], &chatType); err != nil {
		t.Fatalf("chat_type missing or not a string: %v", err)
	}
	return chatType
}

func TestGroupNotificationsCarryChatTypeGroup(t *testing.T) {
	dir := t.TempDir()
	if err := WriteNotification(groupCtx(dir), "3EB0A1", "who booked the venue", "", false, "", ""); err != nil {
		t.Fatalf("write failed: %v", err)
	}
	if chatType := notifChatType(t, dir); chatType != "group" {
		t.Errorf("chat_type = %q, want group: a chat_type=group rule must match group messages", chatType)
	}

	reactionDir := t.TempDir()
	if err := WriteReactionNotification(groupCtx(reactionDir), "3EB0A1", "❤️", false); err != nil {
		t.Fatalf("write failed: %v", err)
	}
	if chatType := notifChatType(t, reactionDir); chatType != "group" {
		t.Errorf("chat_type = %q on a group reaction, want group: a group rule must cover reactions too", chatType)
	}
}

func TestDirectNotificationsCarryChatTypeDirect(t *testing.T) {
	dir := t.TempDir()
	if err := WriteNotification(savedCtx(dir), "3EB0A1", "are you coming", "", false, "", ""); err != nil {
		t.Fatalf("write failed: %v", err)
	}
	if chatType := notifChatType(t, dir); chatType != "direct" {
		t.Errorf("chat_type = %q, want direct: the field is always set so a chat_type!=group rule matches on the value, not on absence", chatType)
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
	var recovery, command, message string
	_ = json.Unmarshal(fields["recovery"], &recovery)
	_ = json.Unmarshal(fields["next_command"], &command)
	_ = json.Unmarshal(fields["message"], &message)
	if recovery != "first_link" || command != "whatsapp connect --source doubletick" || !strings.Contains(message, "now") {
		t.Fatalf("fresh managed notification = recovery %q command %q message %q", recovery, command, message)
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

func TestNamedInstanceUsesItsOwnPersistedRecoveryState(t *testing.T) {
	dir := prepareAuthNotificationTest(t)
	instance := "personal"
	instanceDir := stateDataDirFor(instance)
	if err := os.MkdirAll(instanceDir, 0700); err != nil {
		t.Fatal(err)
	}
	newStateStore(instanceDir).update(func(state *daemonState) {
		state.DirectURL = "https://doubletick.example"
		state.DirectKey = "wak_secret"
		state.OnboardedMSISDN = "+15551230000"
	})

	if err := WriteUnpairedNotification(dir, instance); err != nil {
		t.Fatal(err)
	}
	fields := soleNotifFields(t, dir)
	var approval bool
	var command string
	_ = json.Unmarshal(fields["requires_user_approval"], &approval)
	_ = json.Unmarshal(fields["next_command"], &command)
	if !approval || command != "whatsapp connect --source doubletick --instance 'personal'" {
		t.Fatalf("named-instance recovery = approval %v command %q", approval, command)
	}
}

func TestManagedVMFallbackPrefersCloudOverDirectCredentials(t *testing.T) {
	dir := prepareAuthNotificationTest(t)
	t.Setenv("VESTA_CLOUD_CONTROL_URL", "https://api.vesta.run")
	t.Setenv("DOUBLETICK_API_URL", "https://doubletick.example")
	t.Setenv("DOUBLETICK_API_KEY", "wak_secret")

	if err := WriteUnpairedNotification(dir, ""); err != nil {
		t.Fatal(err)
	}
	fields := soleNotifFields(t, dir)
	var command string
	_ = json.Unmarshal(fields["next_command"], &command)
	if command != "whatsapp connect --source vesta-cloud" {
		t.Fatalf("mixed managed environment selected %q, want vesta-cloud", command)
	}
}

func TestPersistedExplicitSourceWinsInMixedEnvironment(t *testing.T) {
	dir := prepareAuthNotificationTest(t)
	t.Setenv("VESTA_CLOUD_CONTROL_URL", "https://api.vesta.run")
	t.Setenv("DOUBLETICK_API_URL", "https://doubletick.example")
	t.Setenv("DOUBLETICK_API_KEY", "wak_secret")
	newStateStore(stateDataDir()).recordAccountSource(sourceDoubletick)

	if err := WriteUnpairedNotification(dir, ""); err != nil {
		t.Fatal(err)
	}
	fields := soleNotifFields(t, dir)
	var command string
	_ = json.Unmarshal(fields["next_command"], &command)
	if command != "whatsapp connect --source doubletick" {
		t.Fatalf("persisted explicit source produced %q, want doubletick", command)
	}
}

func TestIncompleteDirectConfigBlocksRecoveryCommand(t *testing.T) {
	dir := prepareAuthNotificationTest(t)
	t.Setenv("DOUBLETICK_API_URL", "https://doubletick.example")

	if err := WriteUnpairedNotification(dir, ""); err != nil {
		t.Fatal(err)
	}
	fields := soleNotifFields(t, dir)
	if _, present := fields["next_command"]; present {
		t.Fatal("incomplete credentials produced a connect command that cannot succeed")
	}
	var recovery, message string
	_ = json.Unmarshal(fields["recovery"], &recovery)
	_ = json.Unmarshal(fields["message"], &message)
	if recovery != "configuration_error" || !strings.Contains(message, "must be set together") || strings.Contains(message, "headless") {
		t.Fatalf("incomplete configuration notification = recovery %q message %q", recovery, message)
	}
}
