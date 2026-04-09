package main

import (
	"encoding/json"
	"fmt"
	"net"
	"os"
	"time"
)

type SocketRequest struct {
	Command string   `json:"command"`
	Args    []string `json:"args"`
}

type SocketResponse struct {
	Result any    `json:"result,omitempty"`
	Error  string `json:"error,omitempty"`
}

func startSocketServer(sockPath string, wac *WhatsAppClient) (net.Listener, error) {
	os.Remove(sockPath)

	listener, err := net.Listen("unix", sockPath)
	if err != nil {
		return nil, fmt.Errorf("failed to listen on %s: %v", sockPath, err)
	}

	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			go handleSocketConn(conn, wac)
		}
	}()

	return listener, nil
}

func stopSocketServer(listener net.Listener, sockPath string) {
	listener.Close()
	os.Remove(sockPath)
}

func handleSocketConn(conn net.Conn, wac *WhatsAppClient) {
	defer conn.Close()
	defer func() {
		if r := recover(); r != nil {
			json.NewEncoder(conn).Encode(SocketResponse{Error: fmt.Sprintf("internal error: %v", r)})
		}
	}()

	conn.SetDeadline(time.Now().Add(SocketTimeout))

	var req SocketRequest
	if err := json.NewDecoder(conn).Decode(&req); err != nil {
		json.NewEncoder(conn).Encode(SocketResponse{Error: fmt.Sprintf("invalid request: %v", err)})
		return
	}

	result, err := executeCommand(req.Command, req.Args, wac)

	var resp SocketResponse
	if err != nil {
		resp.Error = err.Error()
	} else {
		resp.Result = result
	}

	json.NewEncoder(conn).Encode(resp)
}

// trySocketCommand attempts to run a command via the serve process's Unix socket.
// Returns (output bytes, exitCode, connected). connected=false means serve isn't running.
func trySocketCommand(sockPath string, command string, args []string) ([]byte, int, bool) {
	conn, err := net.DialTimeout("unix", sockPath, SocketDialTimeout)
	if err != nil {
		return nil, 0, false
	}
	defer conn.Close()

	conn.SetDeadline(time.Now().Add(SocketTimeout))

	if err := json.NewEncoder(conn).Encode(SocketRequest{Command: command, Args: args}); err != nil {
		return nil, 0, false
	}

	var resp SocketResponse
	if err := json.NewDecoder(conn).Decode(&resp); err != nil {
		return nil, 0, false
	}

	if resp.Error != "" {
		data, _ := json.MarshalIndent(map[string]any{"error": resp.Error}, "", "  ")
		return data, 1, true
	}

	data, _ := json.MarshalIndent(resp.Result, "", "  ")
	return data, 0, true
}
