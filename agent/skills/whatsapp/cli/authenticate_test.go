package main

import (
	"encoding/json"
	"net"
	"path/filepath"
	"testing"
)

// startFakeDaemon answers one daemon-status request on sockPath with the given
// live connection state, speaking the same SocketRequest/SocketResponse protocol
// the real serve process uses. It stands in for a logged-in daemon so the auth
// path is exercised end-to-end without a real whatsmeow client.
func startFakeDaemon(t *testing.T, sockPath string, daemonStatus map[string]any) {
	t.Helper()
	listener, err := net.Listen("unix", sockPath)
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	t.Cleanup(func() { listener.Close() })
	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			go func() {
				defer conn.Close()
				var req SocketRequest
				if err := json.NewDecoder(conn).Decode(&req); err != nil {
					return
				}
				json.NewEncoder(conn).Encode(SocketResponse{Result: daemonStatus})
			}()
		}
	}()
}

// TestAuthenticatePrefersLiveDaemonOverStaleCache proves the incident fix: when
// the daemon reports logged_in, `authenticate` reports authenticated even though
// the on-disk state cache still says logged_out.
func TestAuthenticatePrefersLiveDaemonOverStaleCache(t *testing.T) {
	dir := t.TempDir()
	newStateStore(dir).update(func(s *daemonState) {
		s.AuthStatus, s.AuthNote = "logged_out", "left by a prior LoggedOut event"
	})

	sockPath := filepath.Join(dir, "whatsapp.sock")
	startFakeDaemon(t, sockPath, map[string]any{"logged_in": true, "auth_status": string(AuthStatusAuthenticated)})

	got := authStatusResult(sockPath, dir)
	if got["status"] != string(AuthStatusAuthenticated) {
		t.Fatalf("with a logged-in daemon, authenticate must report authenticated, got %q", got["status"])
	}
}

// TestAuthenticateFallsBackToCacheWhenNoDaemon proves the fallback: with no
// daemon answering the socket, authenticate reflects the cached state.
func TestAuthenticateFallsBackToCacheWhenNoDaemon(t *testing.T) {
	dir := t.TempDir()
	newStateStore(dir).update(func(s *daemonState) { s.AuthStatus = "logged_out" })

	got := authStatusResult(filepath.Join(dir, "whatsapp.sock"), dir)
	if got["status"] != "logged_out" {
		t.Fatalf("without a daemon, authenticate must reflect the cache, got %q", got["status"])
	}
}

func TestLiveAuthStatusMapping(t *testing.T) {
	dir := t.TempDir()
	cases := []struct {
		name   string
		status map[string]any
		want   string
	}{
		{"logged in", map[string]any{"logged_in": true, "auth_status": "not_authenticated"}, string(AuthStatusAuthenticated)},
		{"qr ready", map[string]any{"logged_in": false, "auth_status": string(AuthStatusQRReady)}, string(AuthStatusQRReady)},
		{"connecting", map[string]any{"logged_in": false}, string(AuthStatusNotAuthenticated)},
	}
	for _, tc := range cases {
		got := liveAuthStatus(tc.status, dir)
		if got["status"] != tc.want {
			t.Errorf("%s: liveAuthStatus status = %q, want %q", tc.name, got["status"], tc.want)
		}
		if tc.want == string(AuthStatusQRReady) && got["qr_image"] == "" {
			t.Errorf("%s: qr_ready must carry a qr_image path", tc.name)
		}
	}
}
