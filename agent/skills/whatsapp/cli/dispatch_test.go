package main

import "testing"

// TestLookupCommandAliases pins the short-alias-to-canonical resolution that the
// command registry replaced (previously the aliases map in main.go).
func TestLookupCommandAliases(t *testing.T) {
	cases := []struct {
		input string
		want  string
	}{
		{"send", "send-message"},
		{"messages", "list-messages"},
		{"chats", "list-chats"},
		{"contacts", "list-contacts"},
		{"search-contacts", "list-contacts"},
		{"groups", "list-groups"},
		{"file", "send-file"},
		{"react", "send-reaction"},
		{"rename", "rename-group"},
		{"delivery", "check-delivery"},
		{"send-message", "send-message"},
		{"clear-all-chats", "clear-all-chats"},
	}
	for _, c := range cases {
		cmd, ok := lookupCommand(c.input)
		if !ok {
			t.Fatalf("lookupCommand(%q) not found", c.input)
		}
		if cmd.name != c.want {
			t.Errorf("lookupCommand(%q).name = %q, want %q", c.input, cmd.name, c.want)
		}
	}
}

func TestLookupCommandUnknown(t *testing.T) {
	if _, ok := lookupCommand("definitely-not-a-command"); ok {
		t.Error("lookupCommand returned ok for unknown command")
	}
	// serve and authenticate are handled specially in main, not socket commands.
	if _, ok := lookupCommand("serve"); ok {
		t.Error("serve must not be a registry command")
	}
}

// TestCommandWriteFlags pins the read-only block set that the registry replaced
// (previously the writeCommands map in cli.go).
func TestCommandWriteFlags(t *testing.T) {
	writeExpected := map[string]bool{
		"send-message": true, "send-file": true, "send-reaction": true,
		"send-audio": true, "add-contact": true, "remove-contact": true,
		"leave-group": true, "create-group": true, "rename-group": true,
		"update-group-participants": true, "set-group-photo": true, "set-group-description": true,
		"revoke-message": true, "archive-chat": true, "archive-all-chats": true,
		"delete-chat": true, "clear-all-chats": true,
	}
	for _, cmd := range commands {
		want := writeExpected[cmd.name]
		if cmd.write != want {
			t.Errorf("command %q write = %v, want %v", cmd.name, cmd.write, want)
		}
	}
}

// TestCommandPositionals pins the positional-to-flag rewrite specs that the
// registry replaced (previously the positionalSpecs map in main.go).
func TestCommandPositionals(t *testing.T) {
	positionalExpected := map[string][]string{
		"send-message":          {"to", "message"},
		"list-messages":         {"to"},
		"send-file":             {"to", "file-path"},
		"send-reaction":         {"to", "message-id", "emoji"},
		"add-contact":           {"name", "phone"},
		"remove-contact":        {"identifier"},
		"leave-group":           {"group"},
		"backfill":              {"to"},
		"rename-group":          {"group", "name"},
		"set-group-description": {"group", "description"},
		"check-delivery":        {"message-id"},
		"delete-chat":           {"to"},
		"archive-chat":          {"to"},
	}
	for _, cmd := range commands {
		want := positionalExpected[cmd.name]
		if len(cmd.positionals) != len(want) {
			t.Errorf("command %q positionals = %v, want %v", cmd.name, cmd.positionals, want)
			continue
		}
		for i := range want {
			if cmd.positionals[i] != want[i] {
				t.Errorf("command %q positionals = %v, want %v", cmd.name, cmd.positionals, want)
				break
			}
		}
	}
}
