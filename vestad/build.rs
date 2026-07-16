use std::path::{Path, PathBuf};
use std::process::Command;

const CLOUDFLARED_DOWNLOAD_BASE: &str =
    "https://github.com/cloudflare/cloudflared/releases/latest/download";

const RESTIC_VERSION: &str = "0.18.1";
const RESTIC_DOWNLOAD_BASE: &str = "https://github.com/restic/restic/releases/download";

/// Recursively collect embeddable files under `path` (a dir or single file), skipping the
/// __pycache__/*.pyc that rust-embed also excludes, so the hash tracks real source changes.
fn collect_embed_inputs(path: &Path, out: &mut Vec<PathBuf>) {
    if path.is_file() {
        out.push(path.to_path_buf());
        return;
    }
    let Ok(entries) = std::fs::read_dir(path) else {
        return;
    };
    for entry in entries.flatten() {
        let p = entry.path();
        let name = entry.file_name();
        if name == "__pycache__"
            || name == ".venv"
            || name == "node_modules"
            || name == "generate-index.py"
        {
            continue;
        }
        if p.is_dir() {
            collect_embed_inputs(&p, out);
        } else if p.extension().is_none_or(|ext| ext != "pyc") {
            out.push(p);
        }
    }
}

fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-env-changed=VESTAD_SKIP_APP_BUILD");
    println!("cargo:rerun-if-env-changed=VESTAD_SKIP_CLOUDFLARED");
    println!("cargo:rerun-if-env-changed=VESTAD_SKIP_RESTIC");
    println!("cargo:rustc-check-cfg=cfg(cloudflared_vendored)");
    println!("cargo:rustc-check-cfg=cfg(restic_vendored)");

    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let repo_root = manifest_dir
        .parent()
        .expect("vestad/Cargo.toml has a parent");
    let npm_root = repo_root.join("apps");
    let web_dir = npm_root.join("web");

    vendor_cloudflared(&manifest_dir);
    vendor_restic(&manifest_dir);

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
    // rust-embed snapshots files at COMPILE time, and `rerun-if-changed` alone only reruns
    // this script — it does NOT force vestad to recompile, so the embedded snapshot can go
    // stale when agent/core changes but vestad's own sources don't (this silently shipped an
    // old core/ and crash-looped the agent). Hash every embedded input and emit it as a
    // rustc-env that agent_code.rs reads via env!(): when the hash changes, vestad recompiles,
    // rust-embed re-snapshots, and the runtime fingerprint changes so agent-code re-extracts.
    let mut embed_files: Vec<PathBuf> = Vec::new();
    for rel in [
        "agent/core",
        "agent/skills",
        "agent/MEMORY.md",
        "agent/.gitignore",
        "agent/ruff.toml",
    ] {
        collect_embed_inputs(&repo_root.join(rel), &mut embed_files);
    }
    embed_files.sort();
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    for f in &embed_files {
        println!("cargo:rerun-if-changed={}", f.display());
        if let Ok(rel) = f.strip_prefix(repo_root) {
            std::hash::Hasher::write(&mut hasher, rel.to_string_lossy().as_bytes());
        }
        if let Ok(bytes) = std::fs::read(f) {
            std::hash::Hasher::write(&mut hasher, &bytes);
        }
    }
    println!(
        "cargo:rustc-env=VESTAD_EMBED_HASH={:016x}",
        std::hash::Hasher::finish(&hasher)
    );

    // rust-embed stores file content, not modes: extraction would strip the executable
    // bit from skill scripts/binaries, the workspace snapshot would then record 100644
    // for files the image ships as 100755 (mode-diff noise in every box's git status),
    // and a synced binary update would check out non-executable. Record which embedded
    // inputs are executable so agent_code.rs can restore the bit after extraction.
    let mut exec_paths = String::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let agent_root = repo_root.join("agent");
        for f in &embed_files {
            if let (Ok(rel), Ok(meta)) = (f.strip_prefix(&agent_root), std::fs::metadata(f)) {
                if meta.permissions().mode() & 0o111 != 0 {
                    exec_paths.push_str(&rel.to_string_lossy());
                    exec_paths.push('\n');
                }
            }
        }
    }
    let out_dir = std::env::var("OUT_DIR").expect("OUT_DIR is set by cargo");
    std::fs::write(Path::new(&out_dir).join("agent_exec_paths.txt"), exec_paths)
        .expect("write agent_exec_paths.txt");

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
        run_npm(&npm_root, &["install"], &[]);
    }
    run_npm(
        &npm_root,
        &["--workspace", "@vesta/web", "run", "build"],
        &[("VITE_VESTAD_HOSTED", "true")],
    );

    let dist_index = web_dir.join("dist").join("index.html");
    assert!(
        dist_index.exists(),
        "vite build did not produce {}",
        dist_index.display()
    );
}

fn run_npm(cwd: &Path, args: &[&str], env: &[(&str, &str)]) {
    let mut cmd = Command::new("npm");
    cmd.args(args).current_dir(cwd);
    for (k, v) in env {
        cmd.env(k, v);
    }
    match cmd.status() {
        Ok(s) if s.success() => (),
        Ok(s) => panic!("`npm {}` exited with status {s}", args.join(" ")),
        Err(e) => panic!(
            "failed to run `npm {}` in {}: {e}. Install Node.js + npm, or set VESTAD_SKIP_APP_BUILD=1 to skip.",
            args.join(" "),
            cwd.display(),
        ),
    }
}

/// Resolve the vendoring arch suffix (`amd64`/`arm64`) for linux targets, or `None` to skip
/// vendoring (the skip env var is set, a non-linux target, or an unsupported arch).
fn vendor_arch(skip_env: &str) -> Option<&'static str> {
    if std::env::var_os(skip_env).is_some() {
        return None;
    }
    if std::env::var("CARGO_CFG_TARGET_OS").unwrap_or_default() != "linux" {
        return None;
    }
    match std::env::var("CARGO_CFG_TARGET_ARCH")
        .unwrap_or_default()
        .as_str()
    {
        "x86_64" => Some("amd64"),
        "aarch64" => Some("arm64"),
        _ => None,
    }
}

/// Download `url` to `dest` with curl, retrying transient GitHub CDN 502s. Returns whether the
/// download succeeded; panics only if curl itself cannot be spawned.
fn curl_fetch(url: &str, dest: &Path, artifact: &str) -> bool {
    let dest_str = dest
        .to_str()
        .expect("vendored download path is valid UTF-8");
    Command::new("curl")
        .args(["-fsSL", "--retry", "5", "--retry-all-errors", "--retry-delay", "2", "-o", dest_str, url])
        .status()
        .unwrap_or_else(|e| {
            panic!("failed to spawn curl while vendoring {artifact}: {e} (set VESTAD_SKIP_{}=1 to skip)", artifact.to_uppercase())
        })
        .success()
}

fn vendor_cloudflared(manifest_dir: &Path) {
    let Some(arch) = vendor_arch("VESTAD_SKIP_CLOUDFLARED") else {
        return;
    };

    let vendored_dir = manifest_dir.join("vendored");
    let dest = vendored_dir.join("cloudflared");
    println!("cargo:rerun-if-changed={}", dest.display());

    if !dest.exists() {
        std::fs::create_dir_all(&vendored_dir).expect("failed to create vendored dir");
        let url = format!("{CLOUDFLARED_DOWNLOAD_BASE}/cloudflared-linux-{arch}");
        assert!(
            curl_fetch(&url, &dest, "cloudflared"),
            "failed to download cloudflared from {url} (set VESTAD_SKIP_CLOUDFLARED=1 to skip)"
        );
    }

    println!("cargo:rustc-cfg=cloudflared_vendored");
}

fn vendor_restic(manifest_dir: &Path) {
    let Some(arch) = vendor_arch("VESTAD_SKIP_RESTIC") else {
        return;
    };

    let vendored_dir = manifest_dir.join("vendored");
    let dest = vendored_dir.join("restic");
    println!("cargo:rerun-if-changed={}", dest.display());

    if !dest.exists() {
        std::fs::create_dir_all(&vendored_dir).expect("failed to create vendored dir");
        // restic ships each release as a single bzip2-compressed binary. Download
        // and decompress as two explicit steps (no shell pipeline — dash, the
        // default /bin/sh on Debian/Ubuntu, lacks `set -o pipefail`).
        let url = format!(
            "{RESTIC_DOWNLOAD_BASE}/v{RESTIC_VERSION}/restic_{RESTIC_VERSION}_linux_{arch}.bz2"
        );
        let bz2 = vendored_dir.join("restic.bz2");
        if !curl_fetch(&url, &bz2, "restic") {
            std::fs::remove_file(&bz2).ok();
            panic!("failed to download restic from {url} (set VESTAD_SKIP_RESTIC=1 to skip)");
        }
        // `bunzip2 -f` decompresses restic.bz2 -> restic and removes the .bz2.
        let bz2_str = bz2
            .to_str()
            .expect("vendored restic.bz2 path is valid UTF-8");
        let status = Command::new("bunzip2")
            .args(["-f", bz2_str])
            .status()
            .expect(
                "failed to spawn bunzip2 while vendoring restic (set VESTAD_SKIP_RESTIC=1 to skip)",
            );
        if !status.success() {
            std::fs::remove_file(&bz2).ok();
            std::fs::remove_file(&dest).ok();
            panic!("failed to decompress restic (set VESTAD_SKIP_RESTIC=1 to skip)");
        }
    }

    println!("cargo:rustc-cfg=restic_vendored");
}
