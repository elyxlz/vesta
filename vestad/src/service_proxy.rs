use axum::{body::Body, http::StatusCode, Json, response::Response};

/// Rewrite relative asset references in proxied HTML to carry the auth token,
/// so the browser's sub-resource requests pass through the normal auth flow.
///
/// Any skill that registers a web UI service (dashboard, admin panels, etc.)
/// gets its HTML loaded in the app's iframe. The initial request carries
/// `?token=` but browser-initiated sub-resource loads (JS/CSS) cannot.
/// This rewrites relative `src` and `href` attributes to include the token.
fn inject_token_into_html(html: &str, token: &str) -> String {
    let encoded = crate::docker::percent_encode(token);
    let token_suffix = format!("?token={encoded}");
    let mut out = String::with_capacity(html.len() + token_suffix.len() * 4);
    let mut remaining = html;
    loop {
        let src_pos = remaining.find("src=\"");
        let href_pos = remaining.find("href=\"");
        let (attr_start, attr_len) = match (src_pos, href_pos) {
            (Some(s), Some(h)) if s <= h => (s, "src=\"".len()),
            (_, Some(h)) => (h, "href=\"".len()),
            (Some(s), None) => (s, "src=\"".len()),
            (None, None) => break,
        };
        let value_start = attr_start + attr_len;
        out.push_str(&remaining[..value_start]);
        let after_quote = &remaining[value_start..];
        if after_quote.starts_with("./") {
            if let Some(close) = after_quote.find('"') {
                out.push_str(&after_quote[..close]);
                out.push_str(&token_suffix);
                remaining = &after_quote[close..];
            } else {
                out.push_str(after_quote);
                remaining = "";
            }
        } else {
            remaining = after_quote;
        }
    }
    out.push_str(remaining);
    out
}

/// Extract the auth token from the query string.
pub fn extract_token(uri: &axum::http::Uri) -> Option<String> {
    uri.query()
        .and_then(|q| q.split('&').find_map(|p| p.strip_prefix("token=")))
        .map(|t| t.to_string())
}

/// If the response is HTML, rewrite relative asset URLs to include the auth token.
/// No-op for non-HTML responses.
pub async fn rewrite_asset_urls(
    resp: Response,
    token: &str,
) -> Result<Response, (StatusCode, Json<serde_json::Value>)> {
    let is_html = resp
        .headers()
        .get("content-type")
        .map(|ct| ct.as_bytes().starts_with(b"text/html"))
        .unwrap_or(false);

    if !is_html {
        return Ok(resp);
    }

    let (parts, body) = resp.into_parts();
    let body_bytes = axum::body::to_bytes(body, crate::serve::PROXY_MAX_BODY_BYTES)
        .await
        .map_err(|e| {
            (
                StatusCode::BAD_GATEWAY,
                Json(serde_json::json!({"error": format!("read html: {e}")})),
            )
        })?;
    let html = String::from_utf8_lossy(&body_bytes);
    let rewritten = inject_token_into_html(&html, token);
    Ok(Response::from_parts(parts, Body::from(rewritten)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rewrites_relative_assets() {
        let html = r#"<link rel="stylesheet" href="./assets/index-08Wd65qu.css"><script type="module" src="./assets/index-BTqrWaCT.js"></script>"#;
        let result = inject_token_into_html(html, "tok123");
        assert_eq!(
            result,
            r#"<link rel="stylesheet" href="./assets/index-08Wd65qu.css?token=tok123"><script type="module" src="./assets/index-BTqrWaCT.js?token=tok123"></script>"#
        );
    }

    #[test]
    fn ignores_absolute_urls() {
        let html = r#"<script src="https://cdn.example.com/lib.js"></script>"#;
        let result = inject_token_into_html(html, "tok123");
        assert_eq!(result, html);
    }

    #[test]
    fn encodes_special_chars_in_token() {
        let html = r#"<script src="./app.js"></script>"#;
        let result = inject_token_into_html(html, "a b+c");
        assert!(result.contains("?token=a%20b%2Bc"));
    }
}
