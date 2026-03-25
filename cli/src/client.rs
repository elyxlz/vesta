use std::io::{BufRead, Write};

pub use vesta_common::client::{make_ws_rustls_config, Client};

/// Connect to WebSocket and run interactive chat (CLI-only).
pub fn chat(client: &Client, name: &str) -> Result<(), String> {
    let ws_url = client
        .base_url()
        .replace("https://", "wss://")
        .replace("http://", "ws://");
    let url = format!("{}/agents/{}/ws?token={}", ws_url, name, client.api_key());

    let parsed: url::Url =
        url.parse().map_err(|e| format!("invalid ws url: {}", e))?;
    let host = parsed.host_str().unwrap_or("localhost");
    let port = parsed.port().unwrap_or(7860);
    let tcp = std::net::TcpStream::connect((host, port))
        .map_err(|e| format!("ws tcp connect failed: {}", e))?;
    let connector =
        tungstenite::Connector::Rustls(make_ws_rustls_config(client.cert_fingerprint().map(|s| s.to_string())));
    let (mut socket, _) =
        tungstenite::client_tls_with_config(url, tcp, None, Some(connector))
            .map_err(|e| format!("ws connect failed: {}", e))?;

    let (tx, rx) = std::sync::mpsc::channel::<String>();

    let _stdin_handle = std::thread::spawn(move || {
        let stdin = std::io::stdin();
        let mut line = String::new();
        loop {
            line.clear();
            match stdin.lock().read_line(&mut line) {
                Ok(0) => break,
                Ok(_) => {
                    if tx.send(line.trim().to_string()).is_err() {
                        break;
                    }
                }
                Err(_) => break,
            }
        }
    });

    loop {
        if let Ok(input) = rx.try_recv() {
            let msg = serde_json::json!({"type": "message", "content": input});
            if socket
                .send(tungstenite::Message::Text(msg.to_string().into()))
                .is_err()
            {
                break;
            }
        }

        match socket.read() {
            Ok(tungstenite::Message::Text(text)) => {
                if let Ok(msg) = serde_json::from_str::<serde_json::Value>(text.as_ref()) {
                    if let Some(content) = msg["content"].as_str() {
                        print!("{}", content);
                        std::io::stdout().flush().ok();
                    }
                }
            }
            Ok(tungstenite::Message::Close(_)) => break,
            Ok(_) => {}
            Err(tungstenite::Error::ConnectionClosed) => break,
            Err(_) => break,
        }
    }

    Ok(())
}
