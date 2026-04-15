use std::collections::HashMap;
use std::path::Path;

use crate::types::BackupType;

pub const AGENT_CONTAINER_LEGACY_ENABLED: bool = true;

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

pub fn agent_container_legacy_sh() -> &'static str {
    if !AGENT_CONTAINER_LEGACY_ENABLED {
        return "";
    }
    r#"cd ~/vesta && \
     mkdir -p agent .claude && \
     find . -maxdepth 1 -mindepth 1 ! -name agent ! -name .git ! -name .gitignore ! -name .claude ! -name data ! -name logs ! -path './.git.*' 2>/dev/null | while IFS= read -r p; do \
       b=$(basename "$p") && \
       if [ ! -e "agent/$b" ]; then mv "$p" agent/; \
       elif [ -d "$p" ] && [ -d "agent/$b" ]; then \
         find "$p" -mindepth 1 -maxdepth 1 2>/dev/null | while IFS= read -r i; do \
           bn=$(basename "$i") && [ ! -e "agent/$b/$bn" ] && mv "$i" "agent/$b/"; \
         done; \
       fi; \
     done && \
     ([ -d agent/skills ] && ln -sf ../agent/skills .claude/skills) || true && \
     if ! ( git rev-parse --is-inside-work-tree >/dev/null 2>&1 && \
           [ "$(git rev-parse --is-bare-repository 2>/dev/null)" != "true" ] && \
           git sparse-checkout list 2>/dev/null | grep -qE '^agent/?$' ); then \
       ([ -d .git ] && mv .git .git.vesta-migration-backup) || true; \
       git init && \
       (git remote get-url origin >/dev/null 2>&1 || git remote add origin https://github.com/elyxlz/vesta.git) && \
       git sparse-checkout init --cone && git sparse-checkout set agent && \
       printf '/*\n!.gitignore\n!/agent/\n' > .gitignore; \
     fi && \
"#
}

pub fn migrate_legacy_services_json(
    settings_json_path: &Path,
) -> Option<HashMap<String, HashMap<String, u16>>> {
    let old_services = settings_json_path.with_file_name("services.json");
    let data = std::fs::read_to_string(&old_services).ok()?;
    let services: HashMap<String, HashMap<String, u16>> = serde_json::from_str(&data).ok()?;
    if let Err(err) = std::fs::remove_file(&old_services) {
        tracing::warn!(error = %err, "failed to remove old services.json after migration");
    } else {
        tracing::info!("migrated services.json into settings.json");
    }
    Some(services)
}
