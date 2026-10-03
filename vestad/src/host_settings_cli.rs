//! `vestad backup-dir` and `vestad docker-socket`: the two host-layout settings in settings.json.
//! A change stops the service, writes the setting, and starts the service again, so one daemon
//! run never sees two values and never saves its old copy of the settings over the new one.

use std::path::{Path, PathBuf};

#[derive(clap::Subcommand, Debug)]
pub enum HostSettingAction {
    /// Print the value in effect
    Show,
    /// Store a new value
    Set {
        /// The new value
        value: String,
    },
    /// Go back to the default
    Reset,
}

/// Whether moving the repo root from `current` to `target` can go ahead. Repos already in
/// `current` must be moved by hand first: restic finds a repo only by its path, so leaving them
/// behind would empty every agent's restore list.
fn plan_backup_dir(current: &Path, current_has_repos: bool, target: &Path) -> Result<bool, String> {
    if current == target {
        return Ok(false);
    }
    if current_has_repos {
        return Err(format!(
            "backups exist in {current}; move them first: vestad stop && mkdir -p {target} && mv {current}/* {target}/",
            current = current.display(),
            target = target.display(),
        ));
    }
    Ok(true)
}

/// Whether switching the daemon from `current` to `target` can go ahead. Agents live on the
/// daemon that created them, so a switch with agents present would strand every one of them.
fn plan_docker_socket(current: &str, agent_count: usize, target: &str) -> Result<bool, String> {
    if current == target {
        return Ok(false);
    }
    if agent_count > 0 {
        return Err(format!(
            "{agent_count} agent(s) live on the daemon at {current}; changing the socket would strand them. Export or delete them first."
        ));
    }
    Ok(true)
}

fn has_entries(dir: &Path) -> bool {
    std::fs::read_dir(dir).is_ok_and(|mut entries| entries.next().is_some())
}

fn apply_with_service_stopped(
    change: impl FnOnce(&mut crate::settings::Settings),
) -> Result<(), String> {
    let was_active = crate::systemd::is_active();
    if was_active {
        crate::systemd::stop()?;
    }
    let mut settings = crate::settings::load_settings();
    change(&mut settings);
    crate::settings::save_settings(&settings);
    if was_active {
        crate::systemd::start()?;
        crate::systemd::wait_for_start()?;
    }
    Ok(())
}

pub fn run_backup_dir(action: HostSettingAction) -> Result<String, String> {
    let current = crate::restic::repo_root();
    let stored = match action {
        HostSettingAction::Show => return Ok(current.display().to_string()),
        HostSettingAction::Reset => None,
        HostSettingAction::Set { value } => {
            let dir = PathBuf::from(value);
            if !dir.is_absolute() {
                return Err(format!("{} is not an absolute path", dir.display()));
            }
            if !dir.is_dir() {
                return Err(format!(
                    "{} is not a directory; create it (and mount its disk) first",
                    dir.display()
                ));
            }
            Some(dir)
        }
    };
    let target = crate::restic::repo_root_for(stored.clone());
    if plan_backup_dir(&current, has_entries(&current), &target)? {
        apply_with_service_stopped(|settings| settings.backup.repo_dir = stored)?;
    }
    Ok(format!("backups go to {}", target.display()))
}

pub fn run_docker_socket(action: HostSettingAction, agents_dir: &Path) -> Result<String, String> {
    let current = crate::docker::configured_socket().map_err(|e| e.to_string())?;
    let stored = match action {
        HostSettingAction::Show => return Ok(current),
        HostSettingAction::Reset => None,
        HostSettingAction::Set { value } => Some(value),
    };
    let target = crate::docker::socket_for(stored.as_deref()).map_err(|e| e.to_string())?;
    let agent_count = crate::docker::env_file_names(agents_dir).len();
    if plan_docker_socket(&current, agent_count, &target)? {
        apply_with_service_stopped(|settings| settings.docker_socket = stored)?;
    }
    Ok(format!("vestad talks to docker at {target}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn backup_dir_moves_when_the_current_root_holds_no_repos() {
        assert_eq!(
            plan_backup_dir(Path::new("/a"), false, Path::new("/b")),
            Ok(true)
        );
    }

    #[test]
    fn backup_dir_refuses_to_leave_repos_behind_and_names_the_move() {
        let err = plan_backup_dir(Path::new("/a"), true, Path::new("/b")).unwrap_err();
        assert!(err.contains("mv /a/* /b/"));
    }

    #[test]
    fn backup_dir_to_the_same_root_is_a_no_op_even_with_repos() {
        assert_eq!(
            plan_backup_dir(Path::new("/a"), true, Path::new("/a")),
            Ok(false)
        );
    }

    #[test]
    fn docker_socket_switches_when_no_agents_exist() {
        assert_eq!(
            plan_docker_socket("unix:///a.sock", 0, "unix:///b.sock"),
            Ok(true)
        );
    }

    #[test]
    fn docker_socket_refuses_to_strand_agents() {
        let err = plan_docker_socket("unix:///a.sock", 2, "unix:///b.sock").unwrap_err();
        assert!(err.contains("2 agent(s)"));
    }

    #[test]
    fn docker_socket_to_the_same_daemon_is_a_no_op_even_with_agents() {
        assert_eq!(
            plan_docker_socket("unix:///a.sock", 2, "unix:///a.sock"),
            Ok(false)
        );
    }
}
