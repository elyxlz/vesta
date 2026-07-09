package main

import (
	"context"
	"errors"
	"strings"
	"testing"
)

func TestFriendlySendErrorNames463(t *testing.T) {
	err := errors.New("server returned error 463: no signal session established")
	msg := friendlySendError(err)
	if !strings.Contains(msg, "463") || !strings.Contains(msg, "do NOT re-pair") {
		t.Errorf("463 must map to a named, actionable message, got %q", msg)
	}
}

func TestFriendlySendErrorTimeout(t *testing.T) {
	msg := friendlySendError(context.DeadlineExceeded)
	if !strings.Contains(msg, "stalled") {
		t.Errorf("timeout must be explained as a stall, got %q", msg)
	}
}

func TestFriendlySendErrorPassthrough(t *testing.T) {
	msg := friendlySendError(errors.New("some other failure"))
	if !strings.Contains(msg, "some other failure") {
		t.Errorf("unknown errors must pass through, got %q", msg)
	}
}
