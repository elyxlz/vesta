package main

import (
	"testing"

	"go.mau.fi/whatsmeow/types"
)

func TestOwnProfilePictureIQRemove(t *testing.T) {
	query := ownProfilePictureIQ(nil)
	if query.Namespace != "w:profile:picture" || query.Type != "set" || query.To != types.ServerJID {
		t.Fatalf("unexpected remove query: %+v", query)
	}
	if query.Target != (types.JID{}) {
		t.Fatalf("own-photo removal must not carry target: %v", query.Target)
	}
	if query.Content != nil {
		t.Fatalf("photo removal content = %#v, want nil", query.Content)
	}
}

func TestFreshPhotoWipeStateRoundTrip(t *testing.T) {
	dir := t.TempDir()
	store := newStateStore(dir)
	store.update(func(s *daemonState) { s.FreshPhotoWipePending = true })
	if !loadStateFromDisk(dir).FreshPhotoWipePending {
		t.Fatal("fresh photo wipe pending bit was not persisted")
	}
}
