//! The per-agent egress proxy API end to end: vestad installs the sing-box image, checks the
//! proxy, moves the agent into its sidecar's namespace, and hides the password everywhere.
//! Needs Docker and internet (the sing-box download and the preflight to api.anthropic.com).

use vesta_tests::{agent_container_name, docker_cmd, unique_agent, ProxyAuth, TestAgent, SERVER};

const AGENT_RUNNING_TIMEOUT_SECS: u64 = 90;
const TEST_PROXY_PORT: u16 = 1080;
const TEST_PROXY_USER: &str = "egress-user";
const TEST_PROXY_PASSWORD: &str = "egress-secret";

pub(crate) fn sidecar_name(agent: &str) -> String {
    let user = std::env::var("USER").unwrap_or_else(|_| "unknown".to_string());
    format!("vesta-egress-{user}-{agent}")
}

pub(crate) fn agent_network(agent: &str) -> String {
    let user = std::env::var("USER").unwrap_or_else(|_| "unknown".to_string());
    format!("vesta-agent-{user}-{agent}")
}

pub(crate) fn agents_dir() -> std::path::PathBuf {
    SERVER.home_path().join(".config/vesta/vestad/agents")
}

pub(crate) fn network_mode(container: &str) -> String {
    docker_cmd(&["inspect", "-f", "{{.HostConfig.NetworkMode}}", container])
        .expect("inspect network mode")
        .trim()
        .to_string()
}

pub(crate) fn started_at(container: &str) -> String {
    docker_cmd(&["inspect", "-f", "{{.State.StartedAt}}", container])
        .expect("inspect started at")
        .trim()
        .to_string()
}

/// A SOCKS5 proxy on the agent's own network, running the image vestad installed. The host
/// reaches it by container IP (vestad's preflight), and the sidecar reaches it on the shared
/// network. Declare it after the `TestAgent`, so it drops first and frees the network.
pub(crate) struct TestProxy {
    pub(crate) container: String,
    pub(crate) url: String,
    _config_dir: tempfile::TempDir,
}

impl TestProxy {
    pub(crate) fn start(agent: &str) -> Self {
        Self::start_named(agent, "a")
    }

    /// A second proxy for the same agent needs its own container name.
    pub(crate) fn start_named(agent: &str, suffix: &str) -> Self {
        let image = egress_image();
        let config_dir = tempfile::tempdir().expect("tempdir");
        let config_path = config_dir.path().join("proxy.json");
        let config = serde_json::json!({
            "log": {"level": "info"},
            "inbounds": [{
                "type": "socks",
                "listen": "0.0.0.0",
                "listen_port": TEST_PROXY_PORT,
                "users": [{"username": TEST_PROXY_USER, "password": TEST_PROXY_PASSWORD}]
            }],
            "outbounds": [{"type": "direct", "tag": "direct"}]
        });
        std::fs::write(&config_path, config.to_string()).expect("write proxy config");
        let container = format!("egress-test-proxy-{agent}-{suffix}");
        let _ = docker_cmd(&["rm", "-f", &container]);
        docker_cmd(&[
            "run",
            "-d",
            "--name",
            &container,
            "--network",
            &agent_network(agent),
            "-v",
            &format!("{}:/proxy.json:ro", config_path.display()),
            &image,
            "/sing-box",
            "run",
            "-c",
            "/proxy.json",
        ])
        .expect("start test proxy");
        let ip_format = format!(
            "{{{{(index .NetworkSettings.Networks \"{}\").IPAddress}}}}",
            agent_network(agent)
        );
        let ip = docker_cmd(&["inspect", "-f", &ip_format, &container])
            .expect("proxy ip")
            .trim()
            .to_string();
        Self {
            container,
            url: format!("socks5://{TEST_PROXY_USER}:{TEST_PROXY_PASSWORD}@{ip}:{TEST_PROXY_PORT}"),
            _config_dir: config_dir,
        }
    }

    /// How many outbound connections the proxy has opened so far.
    pub(crate) fn connections(&self) -> usize {
        docker_cmd(&["logs", &self.container])
            .unwrap_or_default()
            .matches("outbound connection to")
            .count()
    }
}

impl Drop for TestProxy {
    fn drop(&mut self) {
        let _ = docker_cmd(&["rm", "-f", &self.container]);
    }
}

/// The installed `vesta-egress:<version>` tag. A `PUT` with an unreachable proxy installs the
/// image (it runs before the preflight), so call `install_egress_image` first.
fn egress_image() -> String {
    docker_cmd(&[
        "images",
        "vesta-egress",
        "--format",
        "{{.Repository}}:{{.Tag}}",
    ])
    .expect("list egress images")
    .lines()
    .next()
    .expect("vesta-egress image installed")
    .to_string()
}

/// A dead proxy URL: nothing listens on this port of the documentation address range.
pub(crate) const DEAD_PROXY: &str = "socks5://u:dead-secret@192.0.2.1:1080";

pub(crate) fn install_egress_image(client: &vesta_tests::client::Client, agent: &str) {
    let (status, _) = client.set_proxy(agent, DEAD_PROXY).expect("set dead proxy");
    assert_eq!(
        status, 422,
        "a dead proxy is refused after the image is installed"
    );
}

pub(crate) fn running_agent<'client>(
    client: &'client vesta_tests::client::Client,
    prefix: &str,
) -> TestAgent<'client> {
    let agent = TestAgent::create(client, &unique_agent(prefix)).expect("create agent");
    client.start_agent(&agent.name).expect("start agent");
    client
        .wait_until_running(&agent.name, AGENT_RUNNING_TIMEOUT_SECS)
        .expect("agent running");
    agent
}

#[test]
fn a_dead_proxy_is_refused_and_changes_nothing() {
    let client = SERVER.client();
    let agent = running_agent(&client, "egress-dead");
    let before = network_mode(&agent_container_name(&agent.name));

    let (status, body) = client.set_proxy(&agent.name, DEAD_PROXY).expect("set");
    assert_eq!(status, 422, "{body}");
    assert!(
        !body.contains("dead-secret"),
        "the error must not leak the password: {body}"
    );
    assert_eq!(network_mode(&agent_container_name(&agent.name)), before);
    assert!(!agents_dir().join(format!("{}.proxy", agent.name)).exists());
}

#[test]
fn an_unsupported_scheme_is_a_bad_request() {
    let client = SERVER.client();
    let agent = running_agent(&client, "egress-scheme");
    let (status, _) = client
        .set_proxy(&agent.name, "https://gw.example.com:443")
        .expect("set");
    assert_eq!(status, 400);
}

#[test]
fn the_proxy_routes_are_refused_to_the_agent_token() {
    let client = SERVER.client();
    let agent = running_agent(&client, "egress-token");
    let token = client.read_agent_token(&agent.name).expect("agent token");
    let (status, _) = client
        .get_proxy_as(&agent.name, ProxyAuth::AgentToken(&token))
        .expect("get");
    assert_eq!(status, 401);
}

#[test]
fn set_masks_the_password_and_moves_the_agent_into_its_sidecar() {
    let client = SERVER.client();
    let agent = running_agent(&client, "egress-set");
    install_egress_image(&client, &agent.name);
    let proxy = TestProxy::start(&agent.name);

    let (status, body) = client.set_proxy(&agent.name, &proxy.url).expect("set");
    assert_eq!(status, 200, "{body}");
    assert!(!body.contains(TEST_PROXY_PASSWORD), "{body}");
    assert!(body.contains("***"), "{body}");

    let (status, body) = client
        .get_proxy_as(&agent.name, ProxyAuth::ApiKey)
        .expect("get");
    assert_eq!(status, 200);
    assert!(!body.contains(TEST_PROXY_PASSWORD), "{body}");
    assert!(body.contains(TEST_PROXY_USER), "{body}");

    let sidecar_id = docker_cmd(&["inspect", "-f", "{{.Id}}", &sidecar_name(&agent.name)])
        .expect("sidecar exists")
        .trim()
        .to_string();
    assert_eq!(
        network_mode(&agent_container_name(&agent.name)),
        format!("container:{sidecar_id}")
    );
    client
        .wait_until_running(&agent.name, AGENT_RUNNING_TIMEOUT_SECS)
        .expect("agent running on its sidecar");

    // Review Focus 5: the same URL again changes nothing, so the agent does not restart.
    let before = started_at(&agent_container_name(&agent.name));
    let (status, _) = client
        .set_proxy(&agent.name, &proxy.url)
        .expect("set again");
    assert_eq!(status, 200);
    assert_eq!(started_at(&agent_container_name(&agent.name)), before);

    client.clear_proxy(&agent.name).expect("clear");
    assert_eq!(
        network_mode(&agent_container_name(&agent.name)),
        agent_network(&agent.name)
    );
    assert!(
        docker_cmd(&["inspect", &sidecar_name(&agent.name)]).is_err(),
        "sidecar removed"
    );
    let (_, body) = client
        .get_proxy_as(&agent.name, ProxyAuth::ApiKey)
        .expect("get");
    assert_eq!(body.trim(), r#"{"url":null}"#);
}

#[test]
fn a_stopped_agent_stays_stopped_through_a_proxy_change() {
    let client = SERVER.client();
    let agent = running_agent(&client, "egress-stopped");
    install_egress_image(&client, &agent.name);
    let proxy = TestProxy::start(&agent.name);
    client.stop_agent(&agent.name).expect("stop");
    client
        .wait_until_stopped(&agent.name, AGENT_RUNNING_TIMEOUT_SECS)
        .expect("stopped");

    let (status, body) = client.set_proxy(&agent.name, &proxy.url).expect("set");
    assert_eq!(status, 200, "{body}");
    assert_eq!(
        client.agent_status(&agent.name).expect("status").status,
        "stopped"
    );
    assert!(network_mode(&agent_container_name(&agent.name)).starts_with("container:"));
}
