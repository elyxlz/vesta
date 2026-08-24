package main

import (
	"encoding/json"
	"fmt"
	"net"
	"os"
	"sync/atomic"
	"time"
)

type SocketRequest struct {
	Command string   `json:"command"`
	Args    []string `json:"args"`
}

type SocketResponse struct {
	Result interface{} `json:"result,omitempty"`
	Error  string      `json:"error,omitempty"`
}

// startSocketServer opens the command socket before the daemon has a client, which is what lets
// a daemon that is up but not connected yet answer every caller with that state. The client
// arrives later, so connections read it through the pointer rather than a captured value.
func startSocketServer(sockPath string, client *atomic.Pointer[TelegramClient]) (net.Listener, error) {
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
			go handleSocketConn(conn, client)
		}
	}()

	return listener, nil
}

func stopSocketServer(listener net.Listener, sockPath string) {
	listener.Close()
	os.Remove(sockPath)
}

func handleSocketConn(conn net.Conn, client *atomic.Pointer[TelegramClient]) {
	defer conn.Close()
	defer func() {
		if r := recover(); r != nil {
			json.NewEncoder(conn).Encode(SocketResponse{Error: fmt.Sprintf("internal error: %v", r)})
		}
	}()

	conn.SetDeadline(time.Now().Add(5 * time.Minute))

	var req SocketRequest
	if err := json.NewDecoder(conn).Decode(&req); err != nil {
		json.NewEncoder(conn).Encode(SocketResponse{Error: fmt.Sprintf("invalid request: %v", err)})
		return
	}

	tc := client.Load()
	if tc == nil {
		json.NewEncoder(conn).Encode(SocketResponse{Error: "the daemon is up but not connected to Telegram yet; save a bot token with 'telegram authenticate --token <BOT_TOKEN>' and it connects on its own"})
		return
	}

	result, err := executeCommand(req.Command, req.Args, tc)

	var resp SocketResponse
	if err != nil {
		resp.Error = err.Error()
	} else {
		resp.Result = result
	}

	json.NewEncoder(conn).Encode(resp)
}

func trySocketCommand(sockPath string, command string, args []string) ([]byte, int, bool) {
	conn, err := net.DialTimeout("unix", sockPath, 2*time.Second)
	if err != nil {
		return nil, 0, false
	}
	defer conn.Close()

	conn.SetDeadline(time.Now().Add(5 * time.Minute))

	if err := json.NewEncoder(conn).Encode(SocketRequest{Command: command, Args: args}); err != nil {
		return nil, 0, false
	}

	var resp SocketResponse
	if err := json.NewDecoder(conn).Decode(&resp); err != nil {
		return nil, 0, false
	}

	if resp.Error != "" {
		data, _ := json.Marshal(map[string]interface{}{"error": resp.Error})
		return data, 1, true
	}

	data, _ := json.Marshal(resp.Result)
	return data, 0, true
}
