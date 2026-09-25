//! `vestad proxy`: set, show, or clear an agent's egress proxy through the running daemon's
//! local API, so the CLI and the app share one code path.

/// A proxy change can rebuild a multi-GB agent, which takes minutes.
const REQUEST_TIMEOUT_SECS: u64 = 1800;

#[derive(clap::Subcommand)]
pub enum ProxyAction {
    /// Route the agent's internet traffic through a proxy (http:// or socks5://)
    Set {
        /// Agent name
        agent: String,
        /// Proxy URL, for example <socks5://user:pass@host:1080>
        url: String,
    },
    /// Show the agent's proxy (the password is masked)
    Show {
        /// Agent name
        agent: String,
    },
    /// Stop using a proxy for the agent
    Clear {
        /// Agent name
        agent: String,
    },
}

fn request_line(action: &ProxyAction) -> (reqwest::Method, String, Option<serde_json::Value>) {
    match action {
        ProxyAction::Set { agent, url } => (
            reqwest::Method::PUT,
            format!("/agents/{agent}/proxy"),
            Some(serde_json::json!({ "url": url })),
        ),
        ProxyAction::Show { agent } => {
            (reqwest::Method::GET, format!("/agents/{agent}/proxy"), None)
        }
        ProxyAction::Clear { agent } => (
            reqwest::Method::DELETE,
            format!("/agents/{agent}/proxy"),
            None,
        ),
    }
}

fn success_line(action: &ProxyAction, body: &serde_json::Value) -> String {
    let url = body["url"].as_str();
    match (action, url) {
        (ProxyAction::Set { agent, .. }, Some(url)) => format!("{agent} now uses {url}"),
        (ProxyAction::Show { agent }, Some(url)) => format!("{agent} uses {url}"),
        (
            ProxyAction::Set { agent, .. }
            | ProxyAction::Show { agent }
            | ProxyAction::Clear { agent },
            _,
        ) => {
            format!("{agent} has no proxy")
        }
    }
}

pub fn run(base_url: &str, api_key: &str, action: &ProxyAction) -> Result<String, String> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| format!("could not start the runtime: {e}"))?;
    let (method, path, body) = request_line(action);
    let response_body = runtime.block_on(async {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(REQUEST_TIMEOUT_SECS))
            .build()
            .map_err(|e| format!("could not build the http client: {e}"))?;
        let mut request = client
            .request(method, format!("{base_url}{path}"))
            .bearer_auth(api_key);
        if let Some(body) = body {
            request = request.json(&body);
        }
        let response = request
            .send()
            .await
            .map_err(|e| format!("could not reach vestad (is it running?): {e}"))?;
        let status = response.status();
        let json: serde_json::Value = response.json().await.unwrap_or(serde_json::Value::Null);
        if status.is_success() {
            Ok(json)
        } else {
            Err(json["error"]
                .as_str()
                .map_or_else(|| format!("vestad answered {status}"), str::to_string))
        }
    })?;
    Ok(success_line(action, &response_body))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn each_action_maps_to_its_route() {
        let (method, path, body) = request_line(&ProxyAction::Set {
            agent: "bot".into(),
            url: "socks5://u:p@h:1".into(),
        });
        assert_eq!(
            (method, path.as_str()),
            (reqwest::Method::PUT, "/agents/bot/proxy")
        );
        assert_eq!(body, Some(serde_json::json!({"url": "socks5://u:p@h:1"})));

        let (method, path, body) = request_line(&ProxyAction::Show {
            agent: "bot".into(),
        });
        assert_eq!(
            (method, path.as_str(), body),
            (reqwest::Method::GET, "/agents/bot/proxy", None)
        );

        let (method, path, body) = request_line(&ProxyAction::Clear {
            agent: "bot".into(),
        });
        assert_eq!(
            (method, path.as_str(), body),
            (reqwest::Method::DELETE, "/agents/bot/proxy", None)
        );
    }

    #[test]
    fn success_lines_show_only_the_masked_url() {
        let set = ProxyAction::Set {
            agent: "bot".into(),
            url: "socks5://u:secret@h:1".into(),
        };
        let line = success_line(&set, &serde_json::json!({"url": "socks5://u:***@h:1"}));
        assert_eq!(line, "bot now uses socks5://u:***@h:1");
        assert!(!line.contains("secret"));

        let show = ProxyAction::Show {
            agent: "bot".into(),
        };
        assert_eq!(
            success_line(&show, &serde_json::json!({"url": null})),
            "bot has no proxy"
        );
        assert_eq!(
            success_line(&show, &serde_json::json!({"url": "http://h:8080"})),
            "bot uses http://h:8080"
        );

        let clear = ProxyAction::Clear {
            agent: "bot".into(),
        };
        assert_eq!(
            success_line(&clear, &serde_json::json!({"ok": true})),
            "bot has no proxy"
        );
    }
}
