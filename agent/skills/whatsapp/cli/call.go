package main

import (
	"context"
	"flag"
	"fmt"
	"sync"
	"time"

	meowcaller "github.com/purpshell/meowcaller"
	"go.mau.fi/whatsmeow/types"
)

// A live WhatsApp voice call is Vesta talking to someone on the phone with the same voice as in
// the app. CallManager owns the one active call: it answers inbound calls and places outbound
// ones, and bridges each to one voice engine session (voice_client.go). Each finished turn of the
// other person becomes a `call_utterance` whatsapp notification, so the model responds live
// through the normal interrupt flow. `whatsapp say` sends a line to the engine, which decides
// when it plays and when the other person interrupts it. Only one call runs at a time; a second
// inbound call is rejected while one is active. meowcaller carries the VoIP signaling and media
// on the connected whatsmeow client; this manager holds no codec, turn, or provider logic.

const (
	// How long to wait for the far end to answer an outbound call before giving up.
	outboundAnswerTimeout = 45 * time.Second
)

type activeCall struct {
	call         *meowcaller.Call
	peer         types.JID
	contactName  string
	contactPhone string
	direction    string
	baseURL      string
	ctx          context.Context
	cancel       context.CancelFunc
	// voice is the call's voice engine session. It connects when the bridge starts.
	voice    *voiceSession
	answered bool
	endOnce  sync.Once
}

type CallManager struct {
	mc  *meowcaller.Client
	wac *WhatsAppClient
	mu  sync.Mutex
	// active is the single in-flight call, or nil when idle.
	active *activeCall
}

// NewCallManager wraps the connected whatsmeow client with meowcaller and starts listening for
// inbound calls. It is created once, in the serve path, after the client is connected.
func NewCallManager(wac *WhatsAppClient) *CallManager {
	cm := &CallManager{
		mc:  meowcaller.NewClient(wac.client),
		wac: wac,
	}
	cm.mc.OnIncomingCall(cm.handleIncoming)
	return cm
}

func (cm *CallManager) instance() string { return cm.wac.instance }

func (cm *CallManager) notifyCall(n callNotif) {
	if err := writeCallNotification(cm.wac.notificationsDir, cm.instance(), n); err != nil {
		cm.wac.logger.Warnf("failed to write %s notification: %v", n.Type, err)
	}
}

// displayFor resolves a peer JID to a contact name and phone for notifications.
func (cm *CallManager) displayFor(jid types.JID) (string, string) {
	name := cm.wac.getChatName(jid)
	phone := ""
	if jid.User != "" {
		phone = "+" + jid.User
	}
	return name, phone
}

func (cm *CallManager) handleIncoming(call *meowcaller.Call) {
	peer := call.Peer()
	name, phone := cm.displayFor(peer)

	cm.mu.Lock()
	if cm.active != nil {
		cm.mu.Unlock()
		_ = call.Reject()
		cm.notifyCall(callNotif{Type: "call_missed", Direction: "inbound", ContactName: name, ContactPhone: phone, Reason: "already on another call"})
		return
	}

	baseURL, err := resolveVoiceBaseURL(context.Background())
	if err != nil {
		cm.mu.Unlock()
		_ = call.Reject()
		cm.notifyCall(callNotif{Type: "call_missed", Direction: "inbound", ContactName: name, ContactPhone: phone, Reason: err.Error()})
		return
	}

	if err := call.Answer(); err != nil {
		cm.mu.Unlock()
		cm.wac.logger.Warnf("failed to answer inbound call: %v", err)
		cm.notifyCall(callNotif{Type: "call_missed", Direction: "inbound", ContactName: name, ContactPhone: phone, Reason: "answer failed"})
		return
	}

	ac := cm.beginLocked(call, peer, name, phone, "inbound", baseURL)
	ac.answered = true
	cm.mu.Unlock()

	cm.startBridge(ac)
	cm.notifyCall(callNotif{Type: "call_started", Direction: "inbound", ContactName: name, ContactPhone: phone})
}

// beginLocked records call as the active call. Caller holds cm.mu.
func (cm *CallManager) beginLocked(call *meowcaller.Call, peer types.JID, name, phone, direction, baseURL string) *activeCall {
	ctx, cancel := context.WithCancel(context.Background())
	ac := &activeCall{
		call:         call,
		peer:         peer,
		contactName:  name,
		contactPhone: phone,
		direction:    direction,
		baseURL:      baseURL,
		ctx:          ctx,
		cancel:       cancel,
	}
	ac.voice = newVoiceSession(func(text string) {
		cm.notifyCall(callNotif{Type: "call_utterance", Direction: direction, ContactName: name, ContactPhone: phone, Message: text})
	}, cm.wac.logger.Warnf)
	cm.active = ac
	return ac
}

// Place dials target (a contact name, phone, or JID), waits for the far end to answer, and starts
// the conversation bridge. It blocks until the call is answered, declined, or times out, so it can
// be driven as a single tool call.
func (cm *CallManager) Place(target string) (any, error) {
	if cm.wac.readOnly {
		return nil, fmt.Errorf("cannot place calls: instance is read-only")
	}
	jid, err := cm.wac.ResolveRecipient(target)
	if err != nil {
		return nil, err
	}
	if !isDirectChatJID(jid) {
		return nil, fmt.Errorf("group calls are not supported; call a person, not a group")
	}
	// A voice call is the strongest ban trigger, so it passes the same gate as a text
	// send: a saved contact, and on a managed number a prior inbound (reply-first)
	// before dialing. Checked before touching meowcaller so a blocked call never dials.
	if err := cm.wac.requireSendAllowed(jid); err != nil {
		return nil, err
	}
	name, phone := cm.displayFor(jid)

	cm.mu.Lock()
	if cm.active != nil {
		cm.mu.Unlock()
		return nil, fmt.Errorf("already on a call with %s; hang up first", cm.active.contactName)
	}
	baseURL, err := resolveVoiceBaseURL(context.Background())
	if err != nil {
		cm.mu.Unlock()
		return nil, err
	}

	call, err := cm.mc.Call(context.Background(), phone)
	if err != nil {
		cm.mu.Unlock()
		return nil, fmt.Errorf("failed to place call: %w", err)
	}
	ac := cm.beginLocked(call, jid, name, phone, "outbound", baseURL)

	ready := make(chan struct{}, 1)
	ended := make(chan string, 1)
	call.OnReady(func() {
		select {
		case ready <- struct{}{}:
		default:
		}
	})
	call.OnEnd(func(reason string) {
		select {
		case ended <- reason:
		default:
		}
	})
	cm.mu.Unlock()

	select {
	case <-ready:
		cm.mu.Lock()
		ac.answered = true
		cm.mu.Unlock()
		cm.startBridge(ac)
		return map[string]any{"status": "answered", "contact_name": name, "contact_phone": phone}, nil
	case reason := <-ended:
		cm.endCall(ac, reason)
		return map[string]any{"status": "not_answered", "contact_name": name, "contact_phone": phone, "reason": reason}, nil
	case <-time.After(outboundAnswerTimeout):
		_ = call.Hangup()
		cm.endCall(ac, "no answer")
		return map[string]any{"status": "no_answer", "contact_name": name, "contact_phone": phone}, nil
	}
}

// Say sends text to the call's voice engine session, which speaks it into the call after the
// lines before it. The result says what became of the line: "speaking" when its audio arrived,
// "queued" when none arrived yet (the engine holds a line while the other person has the
// floor), or an error when the line will not play.
func (cm *CallManager) Say(text string) (any, error) {
	cm.mu.Lock()
	ac := cm.active
	if ac == nil || !ac.answered {
		cm.mu.Unlock()
		return nil, fmt.Errorf("no active call to speak into; place or answer a call first")
	}
	cm.mu.Unlock()

	line, err := ac.voice.say(text)
	if ac.ctx.Err() != nil {
		return nil, fmt.Errorf("the call ended before the reply could be spoken")
	}
	if err != nil {
		return nil, err
	}
	return map[string]any{"status": line.status, "contact_name": ac.contactName}, nil
}

// Hangup ends the active call.
func (cm *CallManager) Hangup() (any, error) {
	cm.mu.Lock()
	ac := cm.active
	cm.mu.Unlock()
	if ac == nil {
		return map[string]any{"status": "no_active_call"}, nil
	}
	_ = ac.call.Hangup()
	cm.endCall(ac, "hung up by Vesta")
	return map[string]any{"status": "ended", "contact_name": ac.contactName}, nil
}

// Status reports the active call, or idle.
func (cm *CallManager) Status() (any, error) {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	if cm.active == nil {
		return map[string]any{"active": false}, nil
	}
	ac := cm.active
	return map[string]any{
		"active":        true,
		"direction":     ac.direction,
		"answered":      ac.answered,
		"contact_name":  ac.contactName,
		"contact_phone": ac.contactPhone,
	}, nil
}

// startBridge opens the call's voice engine session and wires the call to it: the peer's audio
// goes up, the call plays the session's speaker, and the bridge comes down when meowcaller
// reports that the call ended. A session that ends while the call is up is logged, and `say`
// reports it.
func (cm *CallManager) startBridge(ac *activeCall) {
	peerAudio := make(chan []byte, peerAudioQueue)

	// The sink runs on meowcaller's decode goroutine and must not block; drop a frame rather than
	// stall decoding if the socket is momentarily behind.
	ac.call.Receive(meowcaller.SinkFunc(func(frame []float32) {
		pcm := floatFrameToPCM16(frame)
		select {
		case peerAudio <- pcm:
		case <-ac.ctx.Done():
		default:
		}
	}))
	ac.call.Play(ac.voice.speaker)

	ac.call.OnEnd(func(reason string) { cm.endCall(ac, reason) })

	go func() {
		err := ac.voice.run(ac.ctx, ac.baseURL, peerAudio)
		if ac.ctx.Err() == nil {
			cm.wac.logger.Warnf("call voice session ended: %v", err)
		}
	}()
}

// endCall tears down the active call exactly once: it cancels the bridge, clears the active slot,
// and reports the end to the model.
func (cm *CallManager) endCall(ac *activeCall, reason string) {
	ac.endOnce.Do(func() {
		ac.cancel()
		cm.mu.Lock()
		if cm.active == ac {
			cm.active = nil
		}
		cm.mu.Unlock()
		cm.notifyCall(callNotif{
			Type:         "call_ended",
			Direction:    ac.direction,
			ContactName:  ac.contactName,
			ContactPhone: ac.contactPhone,
			Reason:       reason,
		})
	})
}

// requireCallMgr guards the call commands: the manager exists only in the serve daemon (it wraps
// the live connection), so a nil here means the command ran outside serve, which never happens via
// the socket but keeps the handlers honest.
func requireCallMgr(wac *WhatsAppClient) (*CallManager, error) {
	if wac.callMgr == nil {
		if wac.readOnly {
			return nil, fmt.Errorf("calling is disabled: instance is read-only")
		}
		return nil, fmt.Errorf("calling is only available from the running daemon")
	}
	return wac.callMgr, nil
}

func cmdCall(args []string, wac *WhatsAppClient) (any, error) {
	var to string
	fs := flag.NewFlagSet("call", flag.ContinueOnError)
	fs.StringVar(&to, "to", "", "Who to call (contact name, phone, or JID)")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	if to == "" {
		return nil, fmt.Errorf("--to is required")
	}
	cm, err := requireCallMgr(wac)
	if err != nil {
		return nil, err
	}
	return cm.Place(to)
}

func cmdSay(args []string, wac *WhatsAppClient) (any, error) {
	var text string
	fs := flag.NewFlagSet("say", flag.ContinueOnError)
	fs.StringVar(&text, "text", "", "What to speak into the call, or '-' to read it from stdin (use a <<'MSG' heredoc for anything with apostrophes or quotes)")
	if err := parseFlags(fs, args); err != nil {
		return nil, err
	}
	// resolveStdinArgs swapped a `-` for the real text in the client process; still seeing one here
	// means nothing was piped in.
	if text == "" || text == "-" {
		return nil, fmt.Errorf("--text is required (pass '-' and a <<'MSG' heredoc to read it from stdin)")
	}
	cm, err := requireCallMgr(wac)
	if err != nil {
		return nil, err
	}
	return cm.Say(text)
}

func cmdHangup(args []string, wac *WhatsAppClient) (any, error) {
	if err := parseNoFlags("hangup", args); err != nil {
		return nil, err
	}
	cm, err := requireCallMgr(wac)
	if err != nil {
		return nil, err
	}
	return cm.Hangup()
}

func cmdCallStatus(args []string, wac *WhatsAppClient) (any, error) {
	if err := parseNoFlags("call-status", args); err != nil {
		return nil, err
	}
	cm, err := requireCallMgr(wac)
	if err != nil {
		return nil, err
	}
	return cm.Status()
}
