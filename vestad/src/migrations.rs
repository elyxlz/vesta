//! Versioned container migrations.
//!
//! Each migration is a function that checks whether it needs to run and applies
//! changes to containers. Migrations run at server startup in order.
//!
//! To add a new migration:
//!   1. Write a `migrate_NNN_description()` function
//!   2. Add it to the `MIGRATIONS` array
//!
//! To deprecate: remove the entry from `MIGRATIONS` once all containers have
//! been migrated past that version (safe to remove after a few releases).

use crate::docker;

struct Migration {
    version: &'static str,
    description: &'static str,
    run: fn(&docker::AgentEnvConfig, &[String]),
}

/// Migrations run in order at startup. Each one is idempotent — it checks
/// whether it needs to run for each container.
const MIGRATIONS: &[Migration] = &[
    Migration {
        version: "0.1.100",
        description: "add read-only code mounts and env file",
        run: migrate_add_mounts_and_env,
    },
];

/// Run all migrations against existing containers.
pub fn run(env_config: &docker::AgentEnvConfig) {
    let containers = docker::list_managed_containers();
    if containers.is_empty() {
        return;
    }

    tracing::info!(
        agents = containers.len(),
        migrations = MIGRATIONS.len(),
        "checking migrations"
    );

    for migration in MIGRATIONS {
        tracing::debug!(
            version = migration.version,
            description = migration.description,
            "running migration"
        );
        (migration.run)(env_config, &containers);
    }
}

// ---------------------------------------------------------------------------
// Migration: add read-only code mounts and env file (v0.1.100)
//
// Pre-migration containers have no bind mounts for src/vesta, pyproject.toml,
// uv.lock and no host env file. This migration:
//   - For containers WITH mounts but missing env file: creates the env file
//   - For containers WITHOUT mounts: rebuilds (commit + recreate) with mounts
// ---------------------------------------------------------------------------

fn migrate_add_mounts_and_env(env_config: &docker::AgentEnvConfig, containers: &[String]) {
    // Check if any container needs mounts — if so, ensure agent code is on host first
    let needs_mounts = containers.iter().any(|c| !docker::has_agent_code_mounts(c));
    if needs_mounts {
        if let Err(e) = crate::agent_code::ensure_agent_code(&env_config.config_dir) {
            tracing::error!(
                migration = "add_mounts_and_env",
                error = %e,
                "failed to ensure agent code on host — cannot migrate containers"
            );
            return;
        }
    }

    for cname in containers {
        let name = docker::get_agent_name(cname);

        if docker::has_agent_code_mounts(cname) {
            // Has mounts — just ensure env file exists
            let env_path = env_config.agents_dir.join(format!("{}.env", name));
            if env_path.exists() {
                continue;
            }

            let port = docker::read_container_env(cname, "WS_PORT")
                .and_then(|v| v.parse::<u16>().ok());
            let Some(port) = port else {
                tracing::warn!(
                    agent = %name,
                    migration = "add_mounts_and_env",
                    "skipped: has mounts but no env file and no WS_PORT in container"
                );
                continue;
            };

            let token = docker::generate_agent_token();
            if let Err(e) = docker::write_agent_env_file(env_config, &name, port, &token) {
                tracing::error!(
                    agent = %name,
                    migration = "add_mounts_and_env",
                    error = %e,
                    "failed to create env file"
                );
                continue;
            }
            tracing::info!(
                agent = %name,
                migration = "add_mounts_and_env",
                port,
                "created missing env file"
            );
            continue;
        }

        // No mounts — needs rebuild (commit filesystem, recreate with new config)
        let was_running = docker::container_status(cname) == docker::ContainerStatus::Running;

        tracing::info!(
            agent = %name,
            migration = "add_mounts_and_env",
            "rebuilding container to add read-only mounts and env file"
        );

        match docker::rebuild_agent(&name, env_config) {
            Ok(()) => {
                tracing::info!(
                    agent = %name,
                    migration = "add_mounts_and_env",
                    "rebuild complete"
                );
            }
            Err(e) => {
                tracing::error!(
                    agent = %name,
                    migration = "add_mounts_and_env",
                    error = %e,
                    "rebuild failed"
                );
                continue;
            }
        }

        // rebuild_agent always starts — stop if it wasn't running before
        if !was_running {
            docker::docker_ok(&["stop", cname]);
        }
    }
}
