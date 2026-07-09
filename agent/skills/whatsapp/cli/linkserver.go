package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/skip2/go-qrcode"
)

const linkServerShutdownTimeout = 3 * time.Second

// All asset URLs are RELATIVE: the page is reached both directly
// (http://localhost:PORT/) and through the vestad tunnel under
// /agents/<name>/wa-link/, and only relative URLs survive both.
const linkPageHTML = `<!doctype html><html><head><meta charset="utf-8"><title>Link WhatsApp</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{background:#111;color:#eee;font-family:sans-serif;text-align:center;padding:24px}
img{width:300px;height:300px;background:#fff;padding:12px;border-radius:8px}
p{opacity:.7;font-size:14px;max-width:360px;margin:16px auto}
#done{display:none;color:#4caf50;font-size:18px}</style></head>
<body><h3>Link WhatsApp</h3><img id="q" src="qr.png" alt="QR code"><div id="done">Linked. You can close this page.</div>
<p>On your phone: WhatsApp &gt; Settings &gt; Linked Devices &gt; Link a Device, then scan. The code refreshes automatically; leave this page open and scan whatever is showing.</p>
<script>
setInterval(function(){document.getElementById('q').src='qr.png?t='+Date.now();},3000);
setInterval(function(){fetch('link-status.json').then(function(r){return r.json()}).then(function(s){
if(s.status==='authenticated'){document.getElementById('q').style.display='none';document.getElementById('done').style.display='block';}});},2000);
</script></body></html>`

// linkHTTPHandler serves the QR link page. Routing is by path SUFFIX because
// the vestad tunnel may or may not strip the /agents/<name>/wa-link prefix.
func (wac *WhatsAppClient) linkHTTPHandler(w http.ResponseWriter, r *http.Request) {
	switch {
	case strings.HasSuffix(r.URL.Path, "/qr.png") || r.URL.Path == "qr.png":
		wac.authMutex.RLock()
		code := wac.currentQRCode
		wac.authMutex.RUnlock()
		if code == "" {
			http.Error(w, "no live QR code; is link mode active?", http.StatusNotFound)
			return
		}
		png, err := qrcode.Encode(code, qrcode.Medium, QRCodeSize)
		if err != nil {
			http.Error(w, "failed to render QR", http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "image/png")
		w.Header().Set("Cache-Control", "no-store")
		w.Write(png)
	case strings.HasSuffix(r.URL.Path, "/link-status.json"):
		status, _ := wac.GetAuthStatus()
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		json.NewEncoder(w).Encode(map[string]string{"status": string(status)})
	default:
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		fmt.Fprint(w, linkPageHTML)
	}
}

func (wac *WhatsAppClient) startLinkServer(port int) {
	server := &http.Server{Addr: fmt.Sprintf("127.0.0.1:%d", port), Handler: http.HandlerFunc(wac.linkHTTPHandler)}
	wac.linkMu.Lock()
	wac.linkServer = server
	wac.linkMu.Unlock()
	go func() {
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			wac.logger.Errorf("link page server failed: %v", err)
		}
	}()
}

func (wac *WhatsAppClient) stopLinkServer() {
	wac.linkMu.Lock()
	server := wac.linkServer
	wac.linkServer = nil
	wac.linkMu.Unlock()
	if server != nil {
		ctx, cancel := context.WithTimeout(context.Background(), linkServerShutdownTimeout)
		defer cancel()
		server.Shutdown(ctx)
	}
}
