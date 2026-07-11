package main

import (
	"context"
	"errors"
	"strings"
	"testing"
)

func TestSendErrorMessageNames463(t *testing.T) {
	err := errors.New("server returned error 463: no signal session established")
	msg := sendErrorMessage("send message", err, SendTimeout)
	if !strings.Contains(msg, "463") || !strings.Contains(msg, "do NOT re-pair") {
		t.Errorf("463 must map to a named, actionable message, got %q", msg)
	}
}

func TestSendErrorMessageTimeout(t *testing.T) {
	msg := sendErrorMessage("send message", context.DeadlineExceeded, SendTimeout)
	if !strings.Contains(msg, "stalled") {
		t.Errorf("timeout must be explained as a stall, got %q", msg)
	}
}

func TestSendErrorMessagePassthrough(t *testing.T) {
	msg := sendErrorMessage("send message", errors.New("some other failure"), SendTimeout)
	if !strings.Contains(msg, "some other failure") {
		t.Errorf("unknown errors must pass through, got %q", msg)
	}
}
