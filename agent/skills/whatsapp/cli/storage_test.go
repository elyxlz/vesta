package main

import (
	"testing"
	"time"
)

func TestStoreAnsweringReportsAHeldConnection(t *testing.T) {
	store := newTestStore(t)
	if !store.Answering(StoreProbeTimeout) {
		t.Fatal("an idle store must answer")
	}
	tx, err := store.Begin()
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback()
	if store.Answering(10 * time.Millisecond) {
		t.Fatal("a store whose only connection is held must not answer")
	}
}
