package main

import (
	"fmt"
	"path/filepath"
	"strings"
)

// pathFlags are the flags whose value is a filesystem path. Commands run inside the daemon, whose
// working directory is not the caller's, so a relative path is resolved here, in the CLI process,
// before it crosses the socket.
var pathFlags = map[string]bool{"file-path": true, "download-path": true, "file": true}

func absolutizePathFlags(args []string) ([]string, error) {
	out := make([]string, len(args))
	copy(out, args)
	for i := 0; i < len(out); i++ {
		name, value, inline := strings.Cut(strings.TrimLeft(out[i], "-"), "=")
		if !strings.HasPrefix(out[i], "-") || !pathFlags[name] {
			continue
		}
		if !inline {
			if i+1 >= len(out) {
				continue
			}
			i++
			value = out[i]
		}
		if value == "" || filepath.IsAbs(value) {
			continue
		}
		abs, err := filepath.Abs(value)
		if err != nil {
			return nil, fmt.Errorf("could not resolve --%s %q: %v", name, value, err)
		}
		if inline {
			out[i] = "--" + name + "=" + abs
		} else {
			out[i] = abs
		}
	}
	return out, nil
}
