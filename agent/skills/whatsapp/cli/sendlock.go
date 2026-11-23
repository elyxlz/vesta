package main

// Serialise sends to the same chat. An agent that emits several `whatsapp send`
// calls in one turn has them run in parallel; each reaches the daemon on its own
// socket connection in its own goroutine (server.go: go handleSocketConn), so two
// sends to one chat race and their bubbles arrive out of order. While a send to a
// chat is in flight, a second send to the same chat is rejected; sequential sends
// never overlap and pass untouched. One process, one mutex: race-free, where a
// per-agent file-locking hook's two instances can both pass. Same reasoning as
// bubblelint: guard the one place every send passes through, not a rule to recall.

import "sync"

var (
	inflightMu    sync.Mutex
	inflightChats = map[string]bool{}
)

// acquireSendSlot marks chat as having an in-flight send and returns true, or
// returns false if a send to the same chat is already in flight (a parallel burst).
func acquireSendSlot(chat string) bool {
	inflightMu.Lock()
	defer inflightMu.Unlock()
	if inflightChats[chat] {
		return false
	}
	inflightChats[chat] = true
	return true
}

// releaseSendSlot clears the in-flight mark for chat.
func releaseSendSlot(chat string) {
	inflightMu.Lock()
	defer inflightMu.Unlock()
	delete(inflightChats, chat)
}

// sendTarget pulls the --to value out of the rewritten args, both "--to X" and
// "--to=X" forms, "" when absent. Keying on the raw target string is enough: a
// burst is the same agent firing the identical --to twice, so the strings match;
// a differing format degrades to the prior behaviour, never a false block.
func sendTarget(args []string) string {
	for i := 0; i < len(args); i++ {
		a := args[i]
		if a == "--to" && i+1 < len(args) {
			return args[i+1]
		}
		if len(a) > 5 && a[:5] == "--to=" {
			return a[5:]
		}
	}
	return ""
}
