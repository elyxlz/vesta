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

  merge_into_agent() {
    src="$1"
    name="$(basename "$src")"
    dest="/root/agent/$name"
    if [ ! -e "$dest" ]; then
      mv "$src" "$dest"
      return
    fi
    if [ -d "$src" ] && [ -d "$dest" ]; then
      for child in "$src"/* "$src"/.[!.]* "$src"/..?*; do
        [ -e "$child" ] || continue
        merge_into_agent "$child"
      done
      rmdir "$src" 2>/dev/null || true
      return
    fi
  }

  for path in /root/vesta/* /root/vesta/.[!.]* /root/vesta/..?*; do
    [ -e "$path" ] || continue
    [ "$(basename "$path")" = ".git" ] && continue
    merge_into_agent "$path"
  done

  for path in /root/data /root/logs /root/notifications; do
    [ -e "$path" ] || continue
    merge_into_agent "$path"
  done

  rm -rf /root/vesta
  rm -rf /root/agent/.claude
  mkdir -p /root/.claude
  ln -sfn ../agent/skills /root/.claude/skills

  rm -rf /root/.git
  git -C /root init
  git -C /root remote add origin https://github.com/elyxlz/vesta.git
  git -C /root sparse-checkout init --cone
  git -C /root sparse-checkout set agent
  printf '%s\n' '/*' '!.gitignore' '!/agent/' > /root/.gitignore
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

async fn normalize_legacy_snapshot_image(
    docker: &Docker,
    image: &str,
    helper_name: &str,
    normalized_tag: &str,
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

    // Rewrite the legacy /root/vesta snapshot in place, then commit the helper
    // container as the normalized image used for the actual rebuild.
    let normalize_result = exec_container_script(docker, helper_name, LEGACY_LAYOUT_NORMALIZE_SCRIPT).await;
    if let Err(err) = normalize_result {
        remove_container_force_if_exists(docker, helper_name).await;
        return Err(err);
    }

    let commit_result = snapshot_container(docker, helper_name, normalized_tag, &[]).await;
    remove_container_force_if_exists(docker, helper_name).await;
    commit_result
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
    normalize_legacy_snapshot_image(docker, snapshot_tag, helper_name, normalized_tag).await?;
    Ok(true)
}
