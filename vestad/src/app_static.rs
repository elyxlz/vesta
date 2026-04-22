use axum::{
    body::Body,
    extract::{Path, State},
    http::{header, StatusCode},
    response::{IntoResponse, Response},
    routing::get,
    Router,
};
use rust_embed::RustEmbed;

use crate::serve::SharedState;

#[derive(RustEmbed)]
#[folder = "../apps/web/dist"]
struct AppAssets;

const IMMUTABLE_CACHE: &str = "public, max-age=31536000, immutable";
const NO_CACHE: &str = "no-cache";
const VESTAD_PORT_PLACEHOLDER: &str = "__VESTAD_PORT__";

pub fn router() -> Router<SharedState> {
    Router::new()
        .route("/app", get(index))
        .route("/app/", get(index))
        .route("/app/{*path}", get(asset))
}

async fn index(State(state): State<SharedState>) -> Response {
    serve_index(state.https_port)
}

async fn asset(State(state): State<SharedState>, Path(path): Path<String>) -> Response {
    if let Some(file) = AppAssets::get(&path) {
        let mime = mime_guess::from_path(&path).first_or_octet_stream();
        let cache = if path.starts_with("assets/") {
            IMMUTABLE_CACHE
        } else {
            NO_CACHE
        };
        return Response::builder()
            .status(StatusCode::OK)
            .header(header::CONTENT_TYPE, mime.as_ref())
            .header(header::CACHE_CONTROL, cache)
            .body(Body::from(file.data.into_owned()))
            .expect("valid static asset response");
    }

    // Treat paths with a file extension as real asset requests: a miss is a 404,
    // not an SPA deep link. Extensionless paths fall through to index.html so
    // React Router can handle them.
    let looks_like_file = path
        .rsplit('/')
        .next()
        .is_some_and(|seg| seg.contains('.'));
    if looks_like_file {
        return (StatusCode::NOT_FOUND, "not found").into_response();
    }

    serve_index(state.https_port)
}

fn serve_index(https_port: u16) -> Response {
    match AppAssets::get("index.html") {
        Some(file) => {
            let html = std::str::from_utf8(&file.data)
                .expect("index.html is valid utf-8")
                .replace(VESTAD_PORT_PLACEHOLDER, &https_port.to_string());
            Response::builder()
                .status(StatusCode::OK)
                .header(header::CONTENT_TYPE, "text/html; charset=utf-8")
                .header(header::CACHE_CONTROL, NO_CACHE)
                .body(Body::from(html))
                .expect("valid index.html response")
        }
        None => (
            StatusCode::NOT_FOUND,
            "vesta app bundle not built — run `npm --workspace @vesta/web run build`",
        )
            .into_response(),
    }
}
