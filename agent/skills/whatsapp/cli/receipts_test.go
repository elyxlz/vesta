package main

import (
	"errors"
	"testing"
)

func TestForceActiveDeliveryReceipts(t *testing.T) {
	if !forceActiveDeliveryReceipts(false) {
		t.Fatal("writable companion must emit visible delivery receipts")
	}
	if forceActiveDeliveryReceipts(true) {
		t.Fatal("read-only companion must not force active delivery receipts")
	}
}

func TestReadReceiptSurvivesPresenceFailure(t *testing.T) {
	presenceFailure := errors.New("no push name")
	marked := false
	presenceErr, receiptErr := sendReadAfterPresence(
		func() error { return presenceFailure },
		func() error { marked = true; return nil },
	)
	if !errors.Is(presenceErr, presenceFailure) {
		t.Fatalf("presence error = %v, want %v", presenceErr, presenceFailure)
	}
	if receiptErr != nil {
		t.Fatalf("read receipt error = %v", receiptErr)
	}
	if !marked {
		t.Fatal("read receipt was skipped after presence failure")
	}
}
