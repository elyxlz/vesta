use axum::{
    body::Body,
    extract::Path,
    http::{header, StatusCode},
    response::{IntoResponse, Response},
    routing::get,
    Router,
};
use rust_embed::RustEmbed;

#[derive(RustEmbed)]
#[folder = "../apps/web/dist"]
struct AppAssets;

const IMMUTABLE_CACHE: &str = "public, max-age=31536000, immutable";
const NO_CACHE: &str = "no-cache";

pub fn router<S>() -> Router<S>
where
    S: Clone + Send + Sync + 'static,
{
    Router::new()
        .route("/app", get(index))
        .route("/app/", get(index))
        .route("/app/{*path}", get(asset))
}

async fn index() -> Response {
    serve_index()
}

async fn asset(Path(path): Path<String>) -> Response {
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

    serve_index()
}

fn serve_index() -> Response {
    match AppAssets::get("index.html") {
        Some(file) => Response::builder()
            .status(StatusCode::OK)
            .header(header::CONTENT_TYPE, "text/html; charset=utf-8")
            .header(header::CACHE_CONTROL, NO_CACHE)
            .body(Body::from(file.data.into_owned()))
            .expect("valid index.html response"),
        None => (
            StatusCode::NOT_FOUND,
            "vesta app bundle not built — run `npm --workspace @vesta/web run build`",
        )
            .into_response(),
    }
}
