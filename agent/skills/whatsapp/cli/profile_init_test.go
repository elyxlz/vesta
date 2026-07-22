package main

import (
	"errors"
	"net/url"
	"strings"
	"testing"

	"go.mau.fi/whatsmeow/types"
)

type provisionTestLinker struct {
	number string
}

func (provisionTestLinker) name() string { return "managed" }
func (l provisionTestLinker) provision(wac *WhatsAppClient) (linkResult, error) {
	wac.client.Store.ID = &types.JID{User: strings.TrimPrefix(l.number, "+"), Server: types.DefaultUserServer}
	return linkResult{MSISDN: l.number}, nil
}
func (provisionTestLinker) linkQR(*WhatsAppClient, int) (linkResult, error) {
	return linkResult{}, errors.New("unused")
}
func (provisionTestLinker) pairCode(*WhatsAppClient, string) (string, error) {
	return "", errors.New("unused")
}

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

func TestCompleteFreshProfileResumesEachPendingStep(t *testing.T) {
	store := newStateStore(t.TempDir())
	store.update(func(s *daemonState) {
		s.FreshNameSetPending = true
		s.FreshPhotoWipePending = true
	})
	var names, photos int
	wac := &WhatsAppClient{
		state:   store,
		managed: newManagedAuth(managedConfig{agentName: "Nova"}),
		setFreshProfileName: func(name string) error {
			names++
			if name != "Nova" {
				t.Fatalf("profile name = %q", name)
			}
			return nil
		},
		removeFreshPhoto: func() error {
			photos++
			if photos == 1 {
				return errors.New("temporary IQ failure")
			}
			return nil
		},
	}
	if err := wac.completeFreshProfile(); err == nil {
		t.Fatal("first profile initialization should surface the photo failure")
	}
	if st := store.snapshot(); st.FreshNameSetPending || !st.FreshPhotoWipePending {
		t.Fatalf("only the successful name step should clear: %+v", st)
	}
	if err := wac.completeFreshProfile(); err != nil {
		t.Fatalf("profile retry: %v", err)
	}
	if st := store.snapshot(); st.FreshNameSetPending || st.FreshPhotoWipePending {
		t.Fatalf("both profile steps should be complete: %+v", st)
	}
	if names != 1 || photos != 2 {
		t.Fatalf("name calls=%d photo calls=%d, want 1 and 2", names, photos)
	}
}

func TestProvisionCommandFirstLinkOpenerAndResume(t *testing.T) {
	for _, tc := range []struct {
		name, opener, want string
	}{
		{"custom opener", "Hello from Nova & friends", "Hello from Nova & friends"},
		{"default opener", "", defaultWelcomeText},
	} {
		t.Run(tc.name, func(t *testing.T) {
			wac := newLinkedTestClient(t)
			wac.client.Store.ID = nil
			wac.linker = provisionTestLinker{number: "+15551230000"}
			wac.setFreshProfileName = func(string) error { return nil }
			wac.removeFreshPhoto = func() error { return nil }
			args := []string{}
			if tc.opener != "" {
				args = []string{"--opener", tc.opener}
			}
			got, err := cmdProvisionManaged(args, wac)
			if err != nil {
				t.Fatalf("cmdProvisionManaged: %v", err)
			}
			next := got.(map[string]any)["next"].(string)
			link := strings.Fields(next[strings.Index(next, "https://wa.me/"):])[0]
			parsed, err := url.Parse(strings.TrimSuffix(link, ","))
			if err != nil {
				t.Fatalf("parse wa.me link: %v", err)
			}
			if text := parsed.Query().Get("text"); text != tc.want {
				t.Fatalf("decoded opener = %q, want %q", text, tc.want)
			}
		})
	}

	wac := newLinkedTestClient(t)
	got, err := cmdProvisionManaged(nil, wac)
	if err != nil {
		t.Fatalf("resume: %v", err)
	}
	if next := got.(map[string]any)["next"].(string); strings.Contains(next, "wa.me/") {
		t.Fatalf("already-linked resume re-emitted onboarding link: %q", next)
	}
}

func TestProvisionCommandRetriesPendingLinkedResult(t *testing.T) {
	wac := newLinkedTestClient(t)
	wac.state.update(func(s *daemonState) {
		s.PendingLinkedResult = true
		s.PendingLinkedOpener = "Please say hello"
		s.FreshPhotoWipePending = true
	})
	wac.removeFreshPhoto = func() error { return nil }
	got, err := cmdProvisionManaged(nil, wac)
	if err != nil {
		t.Fatalf("pending retry: %v", err)
	}
	if next := got.(map[string]any)["next"].(string); !strings.Contains(next, "Please+say+hello") {
		t.Fatalf("pending result lost opener: %q", next)
	}
	if st := wac.state.snapshot(); st.PendingLinkedResult || st.OnboardedMSISDN != "+15551230000" {
		t.Fatalf("pending result was not completed: %+v", st)
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
