use std::path::{Path, PathBuf};
use std::process::Command;

fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-env-changed=VESTAD_SKIP_APP_BUILD");

    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let repo_root = manifest_dir
        .parent()
        .expect("vestad/Cargo.toml has a parent");
    let npm_root = repo_root.join("apps");
    let web_dir = npm_root.join("web");

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
