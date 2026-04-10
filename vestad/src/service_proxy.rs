use axum::{body::Body, http::StatusCode, Json, response::Response};

/// Rewrite relative `src` and `href` attributes in HTML to include the auth token.
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

/// Rewrite relative `url()` references in CSS to include the auth token.
fn inject_token_into_css(css: &str, token: &str) -> String {
    let encoded = crate::docker::percent_encode(token);
    let token_suffix = format!("?token={encoded}");
    let mut out = String::with_capacity(css.len() + token_suffix.len() * 8);
    let mut remaining = css;
    while let Some(pos) = remaining.find("url(") {
        out.push_str(&remaining[..pos + 4]);
        let after = &remaining[pos + 4..];
        let (quote, value_start) = if let Some(rest) = after.strip_prefix('"') {
            (Some('"'), rest)
        } else if let Some(rest) = after.strip_prefix('\'') {
            (Some('\''), rest)
        } else {
            (None, after)
        };
        if value_start.starts_with("./") {
            let close = match quote {
                Some(q) => value_start.find(q),
                None => value_start.find(')'),
            };
            if let Some(end) = close {
                if let Some(q) = quote {
                    out.push(q);
                }
                out.push_str(&value_start[..end]);
                out.push_str(&token_suffix);
                remaining = &value_start[end..];
            } else {
                if let Some(q) = quote {
                    out.push(q);
                }
                remaining = value_start;
            }
        } else {
            if let Some(q) = quote {
                out.push(q);
            }
            remaining = value_start;
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

/// Rewrite relative asset URLs in HTML and CSS responses to include the auth
/// token. No-op for other content types.
pub async fn rewrite_asset_urls(
    resp: Response,
    token: &str,
) -> Result<Response, (StatusCode, Json<serde_json::Value>)> {
    let ct = resp
        .headers()
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");
    let is_html = ct.starts_with("text/html");
    let is_css = ct.starts_with("text/css");

    if !is_html && !is_css {
        return Ok(resp);
    }

    let (parts, body) = resp.into_parts();
    let body_bytes = axum::body::to_bytes(body, crate::serve::PROXY_MAX_BODY_BYTES)
        .await
        .map_err(|e| {
            (
                StatusCode::BAD_GATEWAY,
                Json(serde_json::json!({"error": format!("read body: {e}")})),
            )
        })?;
    let text = String::from_utf8_lossy(&body_bytes);
    let rewritten = if is_html {
        inject_token_into_html(&text, token)
    } else {
        inject_token_into_css(&text, token)
    };
    Ok(Response::from_parts(parts, Body::from(rewritten)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rewrites_relative_html_assets() {
        let html = r#"<link rel="stylesheet" href="./assets/index.css"><script type="module" src="./assets/index.js"></script>"#;
        let result = inject_token_into_html(html, "tok123");
        assert_eq!(
            result,
            r#"<link rel="stylesheet" href="./assets/index.css?token=tok123"><script type="module" src="./assets/index.js?token=tok123"></script>"#
        );
    }

    #[test]
    fn html_ignores_absolute_urls() {
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

    #[test]
    fn rewrites_css_url_unquoted() {
        let css = r#"@font-face{src:url(./assets/font.woff2) format("woff2")}"#;
        let result = inject_token_into_css(css, "tok123");
        assert_eq!(
            result,
            r#"@font-face{src:url(./assets/font.woff2?token=tok123) format("woff2")}"#
        );
    }

    #[test]
    fn rewrites_css_url_double_quoted() {
        let css = r#"@font-face{src:url("./assets/font.woff2") format("woff2")}"#;
        let result = inject_token_into_css(css, "tok123");
        assert_eq!(
            result,
            r#"@font-face{src:url("./assets/font.woff2?token=tok123") format("woff2")}"#
        );
    }

    #[test]
    fn css_ignores_absolute_urls() {
        let css = r#"@import url(https://fonts.googleapis.com/css);"#;
        let result = inject_token_into_css(css, "tok123");
        assert_eq!(result, css);
    }
}
