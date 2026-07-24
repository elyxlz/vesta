package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	waLog "go.mau.fi/whatsmeow/util/log"
)

const (
	daemonLogFile    = "daemon.log"
	daemonLogMaxSize = 5 * 1024 * 1024
)

// writerLogger is a waLog.Logger that writes plain (uncolored) lines to any
// io.Writer, so the daemon's whole log stream can be teed to both stdout and a
// persistent daemon.log. It mirrors whatsmeow's stdout logger format minus the
// ANSI color a log file should not carry. Subloggers share the parent's writer
// and mutex, so lines from every module interleave cleanly on one sink.
type writerLogger struct {
	writer io.Writer
	mutex  *sync.Mutex
	module string
	min    int
}

var logLevelRank = map[string]int{"": -1, "DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}

func newWriterLogger(writer io.Writer, module, minLevel string) *writerLogger {
	return &writerLogger{writer: writer, mutex: &sync.Mutex{}, module: module, min: logLevelRank[strings.ToUpper(minLevel)]}
}

func (l *writerLogger) outputf(level, msg string, args ...any) {
	if logLevelRank[level] < l.min {
		return
	}
	line := fmt.Sprintf("%s [%s %s] %s\n", time.Now().Format("15:04:05.000"), l.module, level, fmt.Sprintf(msg, args...))
	l.mutex.Lock()
	io.WriteString(l.writer, line)
	l.mutex.Unlock()
}

func (l *writerLogger) Errorf(msg string, args ...any) { l.outputf("ERROR", msg, args...) }
func (l *writerLogger) Warnf(msg string, args ...any)  { l.outputf("WARN", msg, args...) }
func (l *writerLogger) Infof(msg string, args ...any)  { l.outputf("INFO", msg, args...) }
func (l *writerLogger) Debugf(msg string, args ...any) { l.outputf("DEBUG", msg, args...) }
func (l *writerLogger) Sub(module string) waLog.Logger {
	return &writerLogger{writer: l.writer, mutex: l.mutex, module: l.module + "/" + module, min: l.min}
}

// openDaemonLog opens (creating if needed) the per-instance daemon.log for
// append, truncating it first when it has grown past daemonLogMaxSize so the
// file is a self-capping log without an external rotation dependency.
func openDaemonLog(dataDir string) (*os.File, error) {
	path := filepath.Join(dataDir, daemonLogFile)
	if info, err := os.Stat(path); err == nil && info.Size() > daemonLogMaxSize {
		if err := os.Truncate(path, 0); err != nil {
			return nil, err
		}
	}
	return os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
}

// serveLogger builds the daemon's logger, teeing to stdout and daemon.log when
// the log file opens, falling back to stdout alone otherwise. The returned
// closer is nil when there is no file to close.
func serveLogger(dataDir string) (waLog.Logger, io.Closer) {
	logFile, err := openDaemonLog(dataDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "warning: could not open daemon.log, logging to stdout only: %v\n", err)
		return newWriterLogger(os.Stdout, "WhatsApp", "WARN"), nil
	}
	sink := io.MultiWriter(os.Stdout, logFile)
	return newWriterLogger(sink, "WhatsApp", "WARN"), logFile
}
