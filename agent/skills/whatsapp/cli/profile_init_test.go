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
	store.update(func(s *daemonState) {
		s.FreshPhotoWipePending = true
		s.FreshNameSetPending = true
	})
	got := loadStateFromDisk(dir)
	if !got.FreshPhotoWipePending || !got.FreshNameSetPending {
		t.Fatalf("fresh profile pending bits were not persisted: %+v", got)
	}
}

func TestManagedProfileName(t *testing.T) {
	for _, tc := range []struct {
		in, want string
	}{
		{" Ada ", "Ada"},
		{"", "Vesta"},
		{"   ", "Vesta"},
	} {
		if got := managedProfileName(tc.in); got != tc.want {
			t.Errorf("managedProfileName(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
}
