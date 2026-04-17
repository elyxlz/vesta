use bollard::container::{Config, CreateContainerOptions, StartContainerOptions};
use bollard::exec::{CreateExecOptions, StartExecResults};
use bollard::Docker;
use futures_util::StreamExt;
use std::collections::HashMap;
use std::path::Path;

use crate::docker::{download_from_container, remove_container_force, snapshot_container, DockerError};
use crate::types::BackupType;

const LEGACY_REPO_ROOT: &str = "/root/vesta";
const LEGACY_MARKER_PATH: &str = "/root/vesta/.git/HEAD";
const ROOT_GIT_MARKER_PATH: &str = "/root/.git/HEAD";
const OLD_SRC_VESTA_MARKER: &str = "/root/agent/src/vesta/main.py";
const NEW_CORE_MARKER: &str = "/root/agent/core/main.py";
const NORMALIZE_HELPER_SLEEP_SECS: &str = "600";
// One-time container-layout migration for pre-agent-dir releases.
//
// Old images stored the repo and worktree directly under /root/vesta. Current
// images expect the git repo at /root with tracked content under /root/agent.
// During rebuild we preserve the old filesystem via docker commit, then run
// this script inside a temporary helper container to rewrite that preserved
// filesystem into the new layout before creating the real rebuilt container.
//
// This intentionally preserves the old files/state while replacing the old git
// metadata with a fresh repo rooted at /root. After a container has been
// normalized once, future rebuilds skip this path entirely.
const LEGACY_LAYOUT_NORMALIZE_SCRIPT: &str = r#"set -euo pipefail
if [ -d /root/vesta/.git ] && [ ! -d /root/.git ]; then
  mkdir -p /root/agent
  shopt -s dotglob nullglob

  merge_dirs() {
    local src="$1" dst="$2"
    mkdir -p "$dst"
    for child in "$src"/* "$src"/.[!.]* "$src"/..?*; do
      [ -e "$child" ] || continue
      local name
      name="$(basename "$child")"
      if [ ! -e "$dst/$name" ]; then
        mv "$child" "$dst/"
      elif [ -d "$child" ] && [ -d "$dst/$name" ]; then
        merge_dirs "$child" "$dst/$name"
      fi
    done
    rmdir "$src" 2>/dev/null || true
  }

  # Only merge ~/vesta/agent/* contents into ~/agent/ — not repo-level files
  if [ -d /root/vesta/agent ]; then
    merge_dirs /root/vesta/agent /root/agent
  fi

  # Move agent-owned paths from ~/vesta/ root (old layouts stored data/logs/notifications here)
  for name in data logs notifications dreamer; do
    for path in /root/vesta/$name /root/$name; do
      [ -d "$path" ] || continue
      merge_dirs "$path" "/root/agent/$name"
    done
  done

  rm -rf /root/vesta
  rm -rf /root/agent/.claude
  mkdir -p /root/.claude
  ln -sfn ../agent/skills /root/.claude/skills

  rm -rf /root/.git
  git -C /root init
  git -C /root remote add origin https://github.com/elyxlz/vesta.git
  git -C /root sparse-checkout init --cone
  SKILL_DIRS=$(cat /root/agent/skills/default-skills.txt 2>/dev/null | sed 's|^|agent/skills/|' | tr '\n' ' ')
  git -C /root sparse-checkout set agent/core agent/prompts agent/dreamer $SKILL_DIRS
  printf '%s\n' '/*' '!.gitignore' '!/agent/' > /root/.gitignore
fi

# Also handle src/vesta → core flatten+rename if present after layout normalization.
# Only moves files into the expected directory structure; the host-mounted code
# (manage_agent_code=true) or new Docker image provides correct source files.
V=/root/agent/src/vesta
if [ -d "$V" ] && [ ! -d /root/agent/core ]; then
  if [ -d "$V/core" ]; then
    for f in "$V"/core/*.py; do
      [ -f "$f" ] || continue
      mv "$f" "$V/$(basename "$f")"
    done
    rm -rf "$V/core"
  fi
  mv "$V" /root/agent/core
  rm -rf /root/agent/src
fi
"#;

pub fn parse_backup_tag_legacy(repo_tag: &str) -> Option<(String, BackupType, String)> {
    if repo_tag.len() < 17 {
        return None;
    }
    let timestamp = &repo_tag[repo_tag.len() - 15..];
    if timestamp.len() != 15 || timestamp.as_bytes()[8] != b'-' {
        return None;
    }
    let name_and_type = &repo_tag[..repo_tag.len() - 16];

    for (suffix, bt) in [
        ("-pre-restore", BackupType::PreRestore),
        ("-manual", BackupType::Manual),
        ("-daily", BackupType::Daily),
        ("-weekly", BackupType::Weekly),
        ("-monthly", BackupType::Monthly),
    ] {
        if let Some(name) = name_and_type.strip_suffix(suffix) {
            if !name.is_empty() {
                return Some((name.to_string(), bt, timestamp.to_string()));
            }
        }
    }
    None
}

pub fn migrate_legacy_services_json(
    settings_json_path: &Path,
) -> Option<HashMap<String, HashMap<String, crate::serve::ServiceEntry>>> {
    let old_services = settings_json_path.with_file_name("services.json");
    let data = std::fs::read_to_string(&old_services).ok()?;
    // Legacy format stored plain u16 ports; new format uses ServiceEntry with public flag
    let legacy: HashMap<String, HashMap<String, u16>> = serde_json::from_str(&data).ok()?;
    let services = legacy
        .into_iter()
        .map(|(agent, svc_map)| {
            let entries = svc_map
                .into_iter()
                .map(|(name, port)| (name, crate::serve::ServiceEntry { port, public: false }))
                .collect();
            (agent, entries)
        })
        .collect();
    if let Err(err) = std::fs::remove_file(&old_services) {
        tracing::warn!(error = %err, "failed to remove old services.json after migration");
    } else {
        tracing::info!("migrated services.json into settings.json");
    }
    Some(services)
}

// Backward compatibility for pre-label managed containers.
//
// Older vestad releases could create managed containers without the
// `vesta.agent_name` label. Those containers still use the long-standing
// `vesta-{user}-{agent}` Docker naming scheme, so newer code can recover the
// logical agent name from the container name during upgrade/list/status flows.
pub fn legacy_agent_name_from_container_name(cname: &str, current_user: &str) -> String {
    let without_vesta = cname.strip_prefix("vesta-").unwrap_or(cname);
    let user_prefix = format!("{current_user}-");
    without_vesta.strip_prefix(&user_prefix).unwrap_or(without_vesta).to_string()
}

// Backward compatibility for pre-label managed containers.
//
// Older vestad releases could also miss the `vesta.user` label entirely.
// During upgrade we still want each server process to see its own old
// containers, but not containers belonging to other users. The legacy name
// prefix is the only ownership signal available in that case.
pub fn legacy_container_owned_by_user(container_name: &str, owner_label: &str, current_user: &str) -> bool {
    owner_label.is_empty() && container_name.starts_with(&format!("vesta-{current_user}-"))
}

// Modern managed-container check.
//
// Current vestad stamps real managed containers with `vesta.user`, so that is
// the primary ownership signal for multi-user filtering.
pub fn modern_container_owned_by_user(owner_label: &str, current_user: &str) -> bool {
    owner_label == current_user
}

async fn container_has_path(docker: &Docker, cname: &str, path: &str) -> bool {
    download_from_container(docker, cname, path).await.is_some()
}

// Runs a one-off migration script inside a temporary helper container created
// from a snapshot image. We use a helper container rather than mutating the
// managed agent container directly so rebuild_agent can keep its snapshot ->
// recreate flow and only publish a fully normalized image once migration
// succeeds.
async fn exec_container_script(docker: &Docker, cname: &str, script: &str) -> Result<String, DockerError> {
    let exec = docker.create_exec(cname, CreateExecOptions {
        cmd: Some(vec!["bash".to_string(), "-lc".to_string(), script.to_string()]),
        attach_stdout: Some(true),
        attach_stderr: Some(true),
        ..Default::default()
    }).await?;

    let mut stdout = String::new();
    let mut output = match docker.start_exec(&exec.id, None).await? {
        StartExecResults::Attached { output, .. } => output,
        StartExecResults::Detached => {
            return Err(DockerError::Failed(format!(
                "exec unexpectedly detached for container {cname}"
            )));
        }
    };

    while let Some(chunk) = output.next().await {
        stdout.push_str(&chunk?.to_string());
    }

    let exit = docker.inspect_exec(&exec.id).await?
        .exit_code
        .unwrap_or_default();
    if exit != 0 {
        return Err(DockerError::Failed(format!(
            "legacy layout normalization failed in {cname} with exit code {exit}: {}",
            stdout.trim()
        )));
    }

    Ok(stdout)
}

async fn remove_container_force_if_exists(docker: &Docker, cname: &str) {
    let _ = remove_container_force(docker, cname).await;
}

async fn run_migration_script(
    docker: &Docker,
    image: &str,
    helper_name: &str,
    normalized_tag: &str,
    script: &str,
) -> Result<(), DockerError> {
    let mut labels = HashMap::new();
    labels.insert("vesta.managed".to_string(), "false".to_string());
    labels.insert("vesta.user".to_string(), "__internal__".to_string());
    labels.insert("vesta.agent_name".to_string(), "__normalize__".to_string());
    let config = Config {
        image: Some(image.to_string()),
        cmd: Some(vec![
            "sleep".to_string(),
            NORMALIZE_HELPER_SLEEP_SECS.to_string(),
        ]),
        labels: Some(labels),
        working_dir: Some("/root".to_string()),
        ..Default::default()
    };
    let create_opts = CreateContainerOptions {
        name: helper_name,
        ..Default::default()
    };

    remove_container_force_if_exists(docker, helper_name).await;
    docker.create_container(Some(create_opts), config).await?;
    docker.start_container(helper_name, None::<StartContainerOptions<String>>).await?;

    let result = exec_container_script(docker, helper_name, script).await;
    if let Err(err) = result {
        remove_container_force_if_exists(docker, helper_name).await;
        return Err(err);
    }

    let commit_result = snapshot_container(docker, helper_name, normalized_tag, &[]).await;
    remove_container_force_if_exists(docker, helper_name).await;
    commit_result
}

// One-time migration for the agent/src/vesta/ → agent/core/ rename.
//
// Pre-0.1.135 images stored Python source at /root/agent/src/vesta/ with a
// nested core/ sub-package. The current layout expects a flat /root/agent/core/.
// During rebuild we flatten and rename the directory structure. No import
// rewriting is needed: with manage_agent_code=true the host-mounted code
// provides correct source files; with manage_agent_code=false the new Docker
// image provides them.
const SRC_VESTA_TO_CORE_SCRIPT: &str = r#"set -euo pipefail
if [ -d /root/agent/src/vesta ] && [ ! -d /root/agent/core ]; then
  V=/root/agent/src/vesta

  # Flatten core/ sub-package into parent
  if [ -d "$V/core" ]; then
    for f in "$V"/core/*.py; do
      [ -f "$f" ] || continue
      mv "$f" "$V/$(basename "$f")"
    done
    rm -rf "$V/core"
  fi

  mv "$V" /root/agent/core
  rm -rf /root/agent/src

  # Update sparse-checkout if it references old paths
  SC=/root/.git/info/sparse-checkout
  if [ -f "$SC" ] && grep -q 'agent/src' "$SC"; then
    sed -i 's|agent/src/vesta|agent/core|g; s|agent/src|agent/core|g' "$SC"
  fi
fi
"#;

pub async fn maybe_rename_src_vesta_to_core(
    docker: &Docker,
    cname: &str,
    snapshot_tag: &str,
    helper_name: &str,
    normalized_tag: &str,
) -> Result<bool, DockerError> {
    let has_old = container_has_path(docker, cname, OLD_SRC_VESTA_MARKER).await;
    let has_new = container_has_path(docker, cname, NEW_CORE_MARKER).await;
    if !has_old || has_new {
        return Ok(false);
    }

    tracing::info!(container = %cname, "migrating agent/src/vesta/ → agent/core/");
    run_migration_script(docker, snapshot_tag, helper_name, normalized_tag, SRC_VESTA_TO_CORE_SCRIPT).await?;

    Ok(true)
}

const OLD_UPSTREAM_SKILL_MARKER: &str = "/root/agent/skills/upstream/SKILL.md";

const REMOVE_OLD_UPSTREAM_SCRIPT: &str = r#"set -euo pipefail
rm -rf /root/agent/skills/upstream

# Fetch replacement skills from upstream if missing
for skill in upstream-sync upstream-pr; do
  if [ ! -d "/root/agent/skills/$skill" ]; then
    git -C /root fetch --depth 1 origin HEAD 2>/dev/null && \
      git -C /root checkout FETCH_HEAD -- "agent/skills/$skill" 2>/dev/null || true
  fi
done
"#;

pub async fn maybe_remove_old_upstream_skill(
    docker: &Docker,
    cname: &str,
    snapshot_tag: &str,
    helper_name: &str,
    normalized_tag: &str,
) -> Result<bool, DockerError> {
    if !container_has_path(docker, cname, OLD_UPSTREAM_SKILL_MARKER).await {
        return Ok(false);
    }

    tracing::info!(container = %cname, "removing old upstream skill (replaced by upstream-sync + upstream-pr)");
    run_migration_script(docker, snapshot_tag, helper_name, normalized_tag, REMOVE_OLD_UPSTREAM_SCRIPT).await?;
    Ok(true)
}

pub async fn maybe_normalize_legacy_agent_snapshot(
    docker: &Docker,
    cname: &str,
    snapshot_tag: &str,
    helper_name: &str,
    normalized_tag: &str,
) -> Result<bool, DockerError> {
    // Only the old /root/vesta layout should take this path. Once a container
    // has been migrated, /root/.git exists and future rebuilds preserve the
    // modern repo/history as-is.
    let needs_legacy_layout_normalization =
        container_has_path(docker, cname, LEGACY_MARKER_PATH).await
        && !container_has_path(docker, cname, ROOT_GIT_MARKER_PATH).await;
    if !needs_legacy_layout_normalization {
        return Ok(false);
    }

    tracing::info!(container = %cname, legacy_root = LEGACY_REPO_ROOT, "normalizing legacy filesystem layout before rebuild");
    run_migration_script(docker, snapshot_tag, helper_name, normalized_tag, LEGACY_LAYOUT_NORMALIZE_SCRIPT).await?;
    Ok(true)
}
