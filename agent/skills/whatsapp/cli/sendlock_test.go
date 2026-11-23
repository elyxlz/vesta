package main

import (
	"sync"
	"testing"
)

func TestSendTargetExtractsTo(t *testing.T) {
	cases := []struct {
		name string
		args []string
		want string
	}{
		{"space form", []string{"--to", "Alice", "--message", "hi"}, "Alice"},
		{"equals form", []string{"--to=Alice", "--message", "hi"}, "Alice"},
		{"to last", []string{"--message", "hi", "--to", "+39123"}, "+39123"},
		{"absent", []string{"--message", "hi"}, ""},
		{"jid value", []string{"--to", "120@g.us", "--message", "x"}, "120@g.us"},
	}
	for _, c := range cases {
		if got := sendTarget(c.args); got != c.want {
			t.Errorf("%s: sendTarget(%v) = %q, want %q", c.name, c.args, got, c.want)
		}
	}
}

func TestSendSlotSerialises(t *testing.T) {
	const chat = "chatA"
	if !acquireSendSlot(chat) {
		t.Fatal("first acquire should succeed")
	}
	if acquireSendSlot(chat) {
		t.Fatal("second acquire while in flight must fail (the parallel-burst block)")
	}
	if !acquireSendSlot("chatB") {
		t.Fatal("a send to a different chat must not be blocked")
	}
	releaseSendSlot(chat)
	releaseSendSlot("chatB")
	if !acquireSendSlot(chat) {
		t.Fatal("acquire after release should succeed (sequential sends pass)")
	}
	releaseSendSlot(chat)
}

// TestSendSlotConcurrentOnlyOneWins proves the lock is race-free: when N
// goroutines race to send to the same chat, exactly one acquires the slot and the
// rest are rejected, which a single-process mutex guarantees and a file lock cannot.
func TestSendSlotConcurrentOnlyOneWins(t *testing.T) {
	const chat = "raceChat"
	const n = 64
	var wg sync.WaitGroup
	var mu sync.Mutex
	winners := 0
	start := make(chan struct{})
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			if acquireSendSlot(chat) {
				mu.Lock()
				winners++
				mu.Unlock()
			}
		}()
	}
	close(start)
	wg.Wait()
	if winners != 1 {
		t.Fatalf("expected exactly 1 goroutine to acquire the slot, got %d", winners)
	}
	releaseSendSlot(chat)
}
