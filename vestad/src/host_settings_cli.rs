//! `vestad backup-dir` and `vestad docker-socket`: the two host-layout settings in settings.json.
//! A change writes the setting while no vestad runs, so one daemon run never sees two values and
//! never saves its old copy of the settings over the new one.

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

/// Apply the change while no vestad runs: a systemd service is stopped and started again, and
/// the `vestad.pid` lock every running vestad holds proves no other one (a `--standalone` run)
/// is up to save its old copy of the settings over the new value.
fn apply_with_vestad_stopped(
    change: impl FnOnce(&mut crate::settings::Settings),
) -> Result<(), String> {
    let was_active = crate::systemd::is_active();
    if was_active {
        crate::systemd::stop()?;
    }
    let written = write_under_vestad_lock(change);
    if was_active {
        crate::systemd::start()?;
        crate::systemd::wait_for_start()?;
    } else if written.is_ok() {
        eprintln!("vestad is not running; it uses the new value when it starts (run `vestad`).");
    }
    written
}

fn write_under_vestad_lock(
    change: impl FnOnce(&mut crate::settings::Settings),
) -> Result<(), String> {
    let _lock = crate::serve::acquire_pid_lock(&crate::paths::config_dir_or_relative()).map_err(|err| {
        format!("{err}; stop the vestad running outside systemd (`vestad serve --standalone`), then run this again")
    })?;
    let mut settings = crate::settings::load_settings();
    change(&mut settings);
    crate::settings::write_settings(&settings)
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
        apply_with_vestad_stopped(|settings| settings.backup.repo_dir = stored)?;
    }
    Ok(format!("backups go to {}", target.display()))
}

pub fn run_docker_socket(action: HostSettingAction, agents_dir: &Path) -> Result<String, String> {
    let stored_now = crate::settings::read_settings().and_then(|settings| settings.docker_socket);
    let current = crate::docker::socket_or_default(stored_now.as_deref()).to_string();
    let stored = match action {
        HostSettingAction::Show => return Ok(current),
        HostSettingAction::Reset => None,
        HostSettingAction::Set { value } => Some(value),
    };
    let target = crate::docker::socket_for(stored.as_deref()).map_err(|e| e.to_string())?;
    let agent_count = crate::docker::env_file_names(agents_dir).len();
    if plan_docker_socket(&current, agent_count, &target)? {
        let socket_path = crate::docker::socket_file(&target);
        if !socket_path.exists() {
            return Err(format!(
                "no docker socket at {}; start that docker daemon first",
                socket_path.display()
            ));
        }
        apply_with_vestad_stopped(|settings| settings.docker_socket = stored)?;
    }
    Ok(format!("vestad talks to docker at {target}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_running_vestads_pid_lock_blocks_the_setter() {
        let dir = tempfile::tempdir().unwrap();
        let _running = crate::serve::acquire_pid_lock(dir.path()).unwrap();
        assert!(crate::serve::acquire_pid_lock(dir.path()).is_err());
    }

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
