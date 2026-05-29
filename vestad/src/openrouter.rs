use crate::serve::{SharedState, err_response};
use axum::{Json, extract::State, http::StatusCode};
use serde::{Deserialize, Serialize};

const TOP_MODELS_URL: &str =
    "https://openrouter.ai/api/frontend/models/find?order=top-weekly";
const TOP_MODELS_LIMIT: usize = 20;

#[derive(Serialize)]
pub struct TopModel {
    pub slug: String,
    pub label: String,
    pub author: String,
    pub context_length: Option<u64>,
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
}

pub async fn list_top_models_handler(
    State(state): State<SharedState>,
) -> Result<Json<Vec<TopModel>>, (StatusCode, Json<serde_json::Value>)> {
    let resp = state
        .http_client
        .get(TOP_MODELS_URL)
        .send()
        .await
        .map_err(|e| err_response(StatusCode::BAD_GATEWAY, &format!("openrouter request failed: {e}")))?;
    if !resp.status().is_success() {
        return Err(err_response(
            StatusCode::BAD_GATEWAY,
            &format!("openrouter returned HTTP {}", resp.status()),
        ));
    }
    let body: FrontendResponse = resp.json().await.map_err(|e| {
        err_response(StatusCode::BAD_GATEWAY, &format!("openrouter response parse failed: {e}"))
    })?;
    let models = body
        .data
        .models
        .into_iter()
        .take(TOP_MODELS_LIMIT)
        .map(|m| TopModel {
            label: m.short_name.or(m.name).unwrap_or_else(|| m.slug.clone()),
            author: m.author_display_name.unwrap_or(m.author),
            slug: m.slug,
            context_length: m.context_length,
        })
        .collect();
    Ok(Json(models))
}
