use std::path::{Path, PathBuf};
use std::process::Command;

const CLOUDFLARED_DOWNLOAD_BASE: &str =
    "https://github.com/cloudflare/cloudflared/releases/latest/download";

fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-env-changed=VESTAD_SKIP_APP_BUILD");
    println!("cargo:rerun-if-env-changed=VESTAD_SKIP_CLOUDFLARED");
    println!("cargo:rustc-check-cfg=cfg(cloudflared_vendored)");

    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let repo_root = manifest_dir
        .parent()
        .expect("vestad/Cargo.toml has a parent");
    let npm_root = repo_root.join("apps");
    let web_dir = npm_root.join("web");

    vendor_cloudflared(&manifest_dir);

    for rel in [
        "src",
        "index.html",
        "package.json",
        "vite.config.ts",
        "tsconfig.json",
    ] {
        let p = web_dir.join(rel);
        if p.exists() {
            println!("cargo:rerun-if-changed={}", p.display());
        }
    }
    let root_lock = npm_root.join("package-lock.json");
    if root_lock.exists() {
        println!("cargo:rerun-if-changed={}", root_lock.display());
    }

    // Agent source is embedded into the binary via rust-embed in src/agent_embed.rs.
    // Rebuild when any embedded input changes so release binaries stay in sync.
    for rel in ["agent/core", "agent/pyproject.toml", "agent/uv.lock"] {
        let p = repo_root.join(rel);
        if p.exists() {
            println!("cargo:rerun-if-changed={}", p.display());
        }
    }

    if std::env::var_os("VESTAD_SKIP_APP_BUILD").is_some() {
        std::fs::create_dir_all(web_dir.join("dist")).ok();
        let placeholder = web_dir.join("dist").join("index.html");
        if !placeholder.exists() {
            std::fs::write(
                &placeholder,
                "<!doctype html><title>vestad</title><body>app build skipped</body>",
            )
            .expect("write placeholder index.html");
        }
        return;
    }

    if !npm_root.join("node_modules").exists() {
        run_npm(&npm_root, &["install"]);
    }
    run_npm(
        &npm_root,
        &["--workspace", "@vesta/web", "run", "build"],
    );

    let dist_index = web_dir.join("dist").join("index.html");
    if !dist_index.exists() {
        panic!("vite build did not produce {}", dist_index.display());
    }
}

fn run_npm(cwd: &Path, args: &[&str]) {
    match Command::new("npm").args(args).current_dir(cwd).status() {
        Ok(s) if s.success() => (),
        Ok(s) => panic!("`npm {}` exited with status {s}", args.join(" ")),
        Err(e) => panic!(
            "failed to run `npm {}` in {}: {e}. Install Node.js + npm, or set VESTAD_SKIP_APP_BUILD=1 to skip.",
            args.join(" "),
            cwd.display(),
        ),
    }
}

fn vendor_cloudflared(manifest_dir: &Path) {
    if std::env::var_os("VESTAD_SKIP_CLOUDFLARED").is_some() {
        return;
    }

    let target_os = std::env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    if target_os != "linux" {
        return;
    }

    let arch = match std::env::var("CARGO_CFG_TARGET_ARCH").unwrap_or_default().as_str() {
        "x86_64" => "amd64",
        "aarch64" => "arm64",
        _ => return,
    };

    let vendored_dir = manifest_dir.join("vendored");
    let dest = vendored_dir.join("cloudflared");
    println!("cargo:rerun-if-changed={}", dest.display());

    if !dest.exists() {
        std::fs::create_dir_all(&vendored_dir)
            .expect("failed to create vendored dir");
        let url = format!("{}/cloudflared-linux-{}", CLOUDFLARED_DOWNLOAD_BASE, arch);
        // GitHub release CDN occasionally 502s; retry on any transient error.
        let status = Command::new("curl")
            .args([
                "-fsSL",
                "--retry", "5",
                "--retry-all-errors",
                "--retry-delay", "2",
                "-o", dest.to_str().unwrap(),
                &url,
            ])
            .status()
            .expect("failed to spawn curl while vendoring cloudflared (set VESTAD_SKIP_CLOUDFLARED=1 to skip)");
        if !status.success() {
            panic!("failed to download cloudflared from {url} (set VESTAD_SKIP_CLOUDFLARED=1 to skip)");
        }
    }

    println!("cargo:rustc-cfg=cloudflared_vendored");
}
