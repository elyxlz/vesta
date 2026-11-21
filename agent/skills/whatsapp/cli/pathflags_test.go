package main

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestAbsolutizePathFlags(t *testing.T) {
	wd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		in, want []string
	}{
		{[]string{"--message-id", "X", "--download-path", "book.pdf"}, []string{"--message-id", "X", "--download-path", filepath.Join(wd, "book.pdf")}},
		{[]string{"--to", "Nour", "--file-path", "/abs/a.pdf"}, []string{"--to", "Nour", "--file-path", "/abs/a.pdf"}},
		{[]string{"--file=sub/p.jpg"}, []string{"--file=" + filepath.Join(wd, "sub/p.jpg")}},
		{[]string{"--to", "file", "--message", "file-path"}, []string{"--to", "file", "--message", "file-path"}},
		{[]string{"--download-path"}, []string{"--download-path"}},
	}
	for _, c := range cases {
		got, err := absolutizePathFlags(c.in)
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(got, c.want) {
			t.Errorf("absolutizePathFlags(%v) = %v, want %v", c.in, got, c.want)
		}
	}
}
