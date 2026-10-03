package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestAbsolutizePathFlags(t *testing.T) {
	wd, _ := os.Getwd()
	args := []string{"--to", "x", "--download-path", "rel/a.pdf", "--file-path=b.docx", "--message", "rel", "--file", "/abs/p.jpg", "-download-path", "-"}
	absolutizePathFlags(args)
	want := []string{"--to", "x", "--download-path", filepath.Join(wd, "rel/a.pdf"), "--file-path=" + filepath.Join(wd, "b.docx"), "--message", "rel", "--file", "/abs/p.jpg", "-download-path", "-"}
	for i := range want {
		if args[i] != want[i] {
			t.Fatalf("arg %d: got %q want %q", i, args[i], want[i])
		}
	}
}
