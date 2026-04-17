use std::time::{Duration, Instant};

use vesta_tests::docker_cmd;

pub fn agent_container_name(user: &str, agent_name: &str) -> Result<String, String> {
    let output = docker_cmd(&[
        "ps",
        "-a",
        "--filter",
        &format!("label=vesta.user={user}"),
        "--filter",
        &format!("label=vesta.agent_name={agent_name}"),
        "--format",
        "{{.Names}}",
    ])?;
    output
        .lines()
        .find(|line| !line.trim().is_empty())
        .map(|line| line.trim().to_string())
        .ok_or_else(|| format!("no managed container found for user={user} agent={agent_name}"))
}

pub fn wait_for_agent_visible<C>(deadline: Instant, mut check: C) -> Result<(), String>
where
    C: FnMut() -> Result<bool, String>,
{
    while Instant::now() < deadline {
        if check()? {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    Err("timed out waiting for upgraded agent state".into())
}
