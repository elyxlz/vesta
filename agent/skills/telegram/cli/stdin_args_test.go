package main

import (
	"os"
	"testing"
)

// withStdin runs fn with os.Stdin replaced by a pipe carrying body.
func withStdin(t *testing.T, body string, fn func()) {
	t.Helper()
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("pipe: %v", err)
	}
	orig := os.Stdin
	os.Stdin = r
	defer func() { os.Stdin = orig; r.Close() }()

	go func() {
		w.WriteString(body)
		w.Close()
	}()
	fn()
}

// The command is executed inside the daemon, which does not share this process's stdin, so the
// body has to be substituted before the args are forwarded. Without this, `--message -` reaches
// the daemon verbatim and the send fails as an empty body.
func TestResolveStdinArgsSubstitutesBodyBeforeForwarding(t *testing.T) {
	cases := []struct {
		name string
		args []string
		body string
		want []string
	}{
		{
			name: "separate value",
			args: []string{"--to", "Ana", "--message", "-"},
			body: "it's me\n",
			want: []string{"--to", "Ana", "--message", "it's me"},
		},
		{
			name: "inline value",
			args: []string{"--to", "Ana", "--message=-"},
			body: "it's me",
			want: []string{"--to", "Ana", "--message=it's me"},
		},
		{
			name: "single dash flag form",
			args: []string{"-message", "-"},
			body: "hi",
			want: []string{"-message", "hi"},
		},
		{
			name: "multi-line body survives intact",
			args: []string{"--message", "-"},
			body: "one\ntwo\n",
			want: []string{"--message", "one\ntwo"},
		},
		{
			name: "a literal message is left alone",
			args: []string{"--message", "hello"},
			body: "unused",
			want: []string{"--message", "hello"},
		},
		{
			name: "a lone dash that is not a body value is left alone",
			args: []string{"--to", "-", "--message", "hi"},
			body: "unused",
			want: []string{"--to", "-", "--message", "hi"},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var got []string
			var err error
			withStdin(t, tc.body, func() { got, err = resolveStdinArgs(tc.args, "message") })
			if err != nil {
				t.Fatalf("resolveStdinArgs: %v", err)
			}
			if len(got) != len(tc.want) {
				t.Fatalf("got %q, want %q", got, tc.want)
			}
			for i := range got {
				if got[i] != tc.want[i] {
					t.Fatalf("got %q, want %q", got, tc.want)
				}
			}
		})
	}
}

// Callers still hold the slice they passed, so the substitution must not write through it.
func TestResolveStdinArgsDoesNotMutateItsInput(t *testing.T) {
	args := []string{"--to", "Ana", "--message", "plain"}
	got, err := resolveStdinArgs(args, "message")
	if err != nil {
		t.Fatalf("resolveStdinArgs: %v", err)
	}
	// The input slice must not be aliased: callers still hold it.
	got[0] = "mutated"
	if args[0] != "--to" {
		t.Fatalf("resolveStdinArgs aliased its input")
	}
}
