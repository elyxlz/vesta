use crate::state::{err_response, SharedState};
use axum::{extract::State, http::StatusCode, Json};
use serde::{Deserialize, Serialize};

const TOP_MODELS_URL: &str = "https://openrouter.ai/api/frontend/models/find?order=top-weekly";
const TOP_MODELS_LIMIT: usize = 20;
const KEY_INFO_URL: &str = "https://openrouter.ai/api/v1/key";
// OpenRouter quotes pricing per token; the picker shows it per million tokens.
const TOKENS_PER_PRICE_UNIT: f64 = 1_000_000.0;

#[derive(Serialize)]
pub struct TopModel {
    pub slug: String,
    pub label: String,
    pub author: String,
    pub context_length: Option<u64>,
    /// USD per million prompt/completion/cache-read tokens, when OpenRouter reports it.
    pub input_price: Option<f64>,
    pub output_price: Option<f64>,
    pub cache_read_price: Option<f64>,
}

#[derive(Deserialize)]
struct FrontendResponse {
    data: FrontendData,
}

#[derive(Deserialize)]
struct FrontendData {
    models: Vec<FrontendModel>,
}

#[derive(Deserialize)]
struct FrontendModel {
    slug: String,
    short_name: Option<String>,
    name: Option<String>,
    author: String,
    author_display_name: Option<String>,
    context_length: Option<u64>,
    endpoint: Option<FrontendEndpoint>,
}

#[derive(Deserialize)]
struct FrontendEndpoint {
    pricing: Option<FrontendPricing>,
}

#[derive(Deserialize)]
struct FrontendPricing {
    prompt: Option<String>,
    completion: Option<String>,
    input_cache_read: Option<String>,
}

// OpenRouter reports per-token prices as decimal strings; convert to USD per million.
fn price_per_million(raw: &Option<String>) -> Option<f64> {
    raw.as_ref()?
        .parse::<f64>()
        .ok()
        .map(|per_token| per_token * TOKENS_PER_PRICE_UNIT)
}

pub async fn list_top_models_handler(
    State(state): State<SharedState>,
) -> Result<Json<Vec<TopModel>>, (StatusCode, Json<serde_json::Value>)> {
    let resp = state
        .http_client
        .get(TOP_MODELS_URL)
        .send()
        .await
        .map_err(|e| {
            err_response(
                StatusCode::BAD_GATEWAY,
                &format!("openrouter request failed: {e}"),
            )
        })?;
    if !resp.status().is_success() {
        return Err(err_response(
            StatusCode::BAD_GATEWAY,
            &format!("openrouter returned HTTP {}", resp.status()),
        ));
    }
    let body: FrontendResponse = resp.json().await.map_err(|e| {
        err_response(
            StatusCode::BAD_GATEWAY,
            &format!("openrouter response parse failed: {e}"),
        )
    })?;
    let models = body
        .data
        .models
        .into_iter()
        .take(TOP_MODELS_LIMIT)
        .map(|m| {
            let pricing = m.endpoint.and_then(|e| e.pricing);
            let (input_price, output_price, cache_read_price) = match pricing {
                Some(p) => (
                    price_per_million(&p.prompt),
                    price_per_million(&p.completion),
                    price_per_million(&p.input_cache_read),
                ),
                None => (None, None, None),
            };
            TopModel {
                label: m.short_name.or(m.name).unwrap_or_else(|| m.slug.clone()),
                author: m.author_display_name.unwrap_or(m.author),
                slug: m.slug,
                context_length: m.context_length,
                input_price,
                output_price,
                cache_read_price,
            }
        })
        .collect();
    Ok(Json(models))
}

#[derive(Deserialize)]
pub struct ValidateKeyBody {
    pub key: String,
}

/// Probes OpenRouter's /api/v1/key with the user-supplied key. 200 means the key
/// is valid; 401 means it isn't. Lets both CLI and web validate before commit.
pub async fn validate_key_handler(
    State(state): State<SharedState>,
    Json(body): Json<ValidateKeyBody>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    let resp = state
        .http_client
        .get(KEY_INFO_URL)
        .bearer_auth(&body.key)
        .send()
        .await
        .map_err(|e| {
            err_response(
                StatusCode::BAD_GATEWAY,
                &format!("openrouter request failed: {e}"),
            )
        })?;
    if resp.status() == reqwest::StatusCode::UNAUTHORIZED {
        return Err(err_response(StatusCode::BAD_REQUEST, "invalid API key"));
    }
    if !resp.status().is_success() {
        return Err(err_response(
            StatusCode::BAD_GATEWAY,
            &format!("openrouter returned HTTP {}", resp.status()),
        ));
    }
    Ok(Json(serde_json::json!({"ok": true})))
}
