//! The per-agent egress proxy API end to end: vestad installs the sing-box image, checks the
//! proxy, moves the agent into its sidecar's namespace, and hides the password everywhere.
//! Needs Docker and internet (the sing-box download and the preflight to api.anthropic.com).

use vesta_tests::{
    agent_container_name, docker_cmd, exec_in_container, unique_agent, ProxyAuth, TestAgent, SERVER,
};

const AGENT_RUNNING_TIMEOUT_SECS: u64 = 90;
const TEST_PROXY_PORT: u16 = 1080;
const TEST_PROXY_USER: &str = "egress-user";
const TEST_PROXY_PASSWORD: &str = "egress-secret";
const PROXY_LISTEN_TIMEOUT_SECS: u64 = 10;

/// Block until `ip:port` accepts a TCP connection, or the timeout passes. `docker run -d`
/// returns as soon as the container starts, not once sing-box's listener is up, and vestad's
/// own preflight can otherwise race ahead of it under back-to-back test runs.
fn wait_for_listener(ip: &str, port: u16) {
    let deadline =
        std::time::Instant::now() + std::time::Duration::from_secs(PROXY_LISTEN_TIMEOUT_SECS);
    loop {
        let addr = format!("{ip}:{port}");
        if let Ok(mut addrs) = std::net::ToSocketAddrs::to_socket_addrs(&addr) {
            if let Some(socket_addr) = addrs.next() {
                if std::net::TcpStream::connect_timeout(
                    &socket_addr,
                    std::time::Duration::from_millis(500),
                )
                .is_ok()
                {
                    return;
                }
            }
        }
        if std::time::Instant::now() >= deadline {
            return;
        }
        std::thread::sleep(std::time::Duration::from_millis(100));
    }
}

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
        wait_for_listener(&ip, TEST_PROXY_PORT);
        Self {
            container,
            url: format!("socks5://{TEST_PROXY_USER}:{TEST_PROXY_PASSWORD}@{ip}:{TEST_PROXY_PORT}"),
            _config_dir: config_dir,
        }
    }

    /// How many outbound connections the proxy has opened so far. sing-box logs to the
    /// container's stderr stream, and `docker logs` replays each stream to the matching
    /// stream of its own process, so this reads both rather than `docker_cmd`'s stdout-only.
    pub(crate) fn connections(&self) -> usize {
        let output = std::process::Command::new("docker")
            .args(["logs", &self.container])
            .output();
        let Ok(output) = output else {
            return 0;
        };
        let combined = [output.stdout, output.stderr].concat();
        String::from_utf8_lossy(&combined)
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

const REQUEST_TIMEOUT_SECS: u64 = 15;
const REPAIR_TIMEOUT_SECS: u64 = 90;

/// The HTTP status of an agent's request to a public site, or the curl failure text.
fn agent_fetch(agent: &str) -> Result<String, String> {
    exec_in_container(
        &agent_container_name(agent),
        &format!("curl -s -m {REQUEST_TIMEOUT_SECS} -o /dev/null -w '%{{http_code}}' https://example.org/"),
    )
}

fn wait_for_fetch(agent: &str, timeout_secs: u64) -> bool {
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(timeout_secs);
    while std::time::Instant::now() < deadline {
        if agent_fetch(agent).is_ok_and(|code| code.trim() == "200") {
            return true;
        }
        std::thread::sleep(std::time::Duration::from_secs(2));
    }
    false
}

fn proxied_agent<'client>(
    client: &'client vesta_tests::client::Client,
    prefix: &str,
) -> (TestAgent<'client>, TestProxy) {
    let agent = running_agent(client, prefix);
    install_egress_image(client, &agent.name);
    let proxy = TestProxy::start(&agent.name);
    let (status, body) = client
        .set_proxy(&agent.name, &proxy.url)
        .expect("set proxy");
    assert_eq!(status, 200, "{body}");
    client
        .wait_until_running(&agent.name, AGENT_RUNNING_TIMEOUT_SECS)
        .expect("agent running on its sidecar");
    (agent, proxy)
}

#[test]
fn agent_traffic_leaves_through_the_proxy() {
    let client = SERVER.client();
    let (agent, proxy) = proxied_agent(&client, "egress-route");
    let before = proxy.connections();

    assert!(
        wait_for_fetch(&agent.name, REQUEST_TIMEOUT_SECS * 2),
        "the agent reaches the internet"
    );
    assert!(
        proxy.connections() > before,
        "the request went through the proxy"
    );
}

/// C1 (the full-block fix): a socket bound straight to `eth0` (`SO_BINDTODEVICE`, which `curl
/// --interface` and this UDP probe both use) skips sing-box's TUN rules entirely, since
/// `auto_route`/`strict_route` only steer sockets that go through the normal routing table
/// lookup. The init script removes eth0's direct default route from the main table, so a
/// bound socket has no direct path to fall back on, whichever way the proxy is doing.
#[test]
fn an_interface_bound_socket_cannot_bypass_the_proxy() {
    let client = SERVER.client();
    let (agent, proxy) = proxied_agent(&client, "egress-bind");
    let cname = agent_container_name(&agent.name);

    assert!(
        wait_for_fetch(&agent.name, REQUEST_TIMEOUT_SECS * 2),
        "ordinary (unbound) traffic must reach the internet through the proxy"
    );

    let eth0_tcp = || exec_in_container(&cname, "curl --interface eth0 -m 8 https://1.1.1.1/");
    assert!(
        eth0_tcp().is_err(),
        "an eth0-bound TCP connection must not reach the internet directly (proxy up)"
    );

    let udp_probe = r#"
python3 - << 'PYEOF'
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b'eth0')
s.settimeout(5)
s.sendto(b'\x1b' + b'\x00' * 47, ('162.159.200.1', 123))
try:
    s.recvfrom(48)
    print('answered')
except socket.timeout:
    print('blocked')
PYEOF
"#;
    let result = exec_in_container(&cname, udp_probe).expect("udp probe ran");
    assert_eq!(
        result.trim(),
        "blocked",
        "an eth0-bound UDP socket must not reach the internet directly (proxy up)"
    );

    docker_cmd(&["stop", &proxy.container]).expect("stop proxy");
    assert!(
        eth0_tcp().is_err(),
        "an eth0-bound TCP connection must not reach the internet directly (proxy stopped)"
    );
}

#[test]
fn the_agent_still_reaches_vestad_directly() {
    let client = SERVER.client();
    let (agent, _proxy) = proxied_agent(&client, "egress-local");
    let code = exec_in_container(
        &agent_container_name(&agent.name),
        ". /run/vestad-env && curl -sk -m 10 -o /dev/null -w '%{http_code}' https://$BOX_HOST:$VESTAD_PORT/health",
    )
    .expect("reach vestad");
    assert_eq!(code.trim(), "200");
}

#[test]
fn a_stopped_proxy_blocks_traffic_instead_of_going_direct() {
    let client = SERVER.client();
    let (agent, proxy) = proxied_agent(&client, "egress-closed");
    docker_cmd(&["stop", &proxy.container]).expect("stop proxy");

    let result = agent_fetch(&agent.name);
    assert!(
        !result.is_ok_and(|code| code.trim() == "200"),
        "with the proxy down, the request must fail"
    );
}

#[test]
fn a_restarted_sidecar_brings_the_agent_back_online() {
    let client = SERVER.client();
    let (agent, _proxy) = proxied_agent(&client, "egress-repair");
    docker_cmd(&["restart", &sidecar_name(&agent.name)]).expect("restart sidecar");

    assert!(
        wait_for_fetch(&agent.name, REPAIR_TIMEOUT_SECS),
        "vestad restarts the agent into the sidecar's new namespace"
    );
    // The repair must also drop the cached bridge IP, or a resolve that hit before the sidecar's
    // restart keeps the tap dialing the dead address and the roster never converges past Starting.
    client
        .wait_until_running(&agent.name, AGENT_RUNNING_TIMEOUT_SECS)
        .expect("agent status converges to running after the repair restart");
}

#[test]
fn a_proxy_given_by_hostname_resolves_and_routes() {
    let client = SERVER.client();
    let agent = running_agent(&client, "egress-hostname");
    install_egress_image(&client, &agent.name);
    let proxy = TestProxy::start(&agent.name);

    // sslip.io maps `a-b-c-d.sslip.io` to `a.b.c.d`, a public DNS name that resolves to the
    // proxy's own container IP, so the sidecar must resolve the proxy's hostname itself.
    let ip_format = format!(
        "{{{{(index .NetworkSettings.Networks \"{}\").IPAddress}}}}",
        agent_network(&agent.name)
    );
    let ip = docker_cmd(&["inspect", "-f", &ip_format, &proxy.container])
        .expect("proxy ip")
        .trim()
        .to_string();
    let hostname = ip.replace('.', "-");
    let url = format!(
        "socks5://{TEST_PROXY_USER}:{TEST_PROXY_PASSWORD}@{hostname}.sslip.io:{TEST_PROXY_PORT}"
    );
    let before = proxy.connections();

    let (status, body) = client.set_proxy(&agent.name, &url).expect("set");
    assert_eq!(status, 200, "{body}");
    client
        .wait_until_running(&agent.name, AGENT_RUNNING_TIMEOUT_SECS)
        .expect("agent running on its sidecar");

    assert!(
        wait_for_fetch(&agent.name, REPAIR_TIMEOUT_SECS),
        "the agent reaches the internet through a proxy given by hostname"
    );
    assert!(
        proxy.connections() > before,
        "the request reached the proxy resolved by its sslip.io hostname"
    );
}

#[test]
fn clearing_the_proxy_of_an_unknown_agent_is_a_404() {
    let client = SERVER.client();
    let (status, _) = client
        .clear_proxy_status(&unique_agent("egress-missing"))
        .expect("delete");
    assert_eq!(status, 404);
}

#[test]
fn a_url_change_reloads_the_sidecar_without_a_rebuild() {
    let client = SERVER.client();
    let (agent, _first) = proxied_agent(&client, "egress-change");
    let sidecar_before =
        docker_cmd(&["inspect", "-f", "{{.Id}}", &sidecar_name(&agent.name)]).expect("sidecar");
    let second = TestProxy::start_named(&agent.name, "b");
    let (status, body) = client.set_proxy(&agent.name, &second.url).expect("change");
    assert_eq!(status, 200, "{body}");

    let sidecar_after =
        docker_cmd(&["inspect", "-f", "{{.Id}}", &sidecar_name(&agent.name)]).expect("sidecar");
    assert_eq!(
        sidecar_before, sidecar_after,
        "a URL change keeps the sidecar"
    );
    let before = second.connections();
    assert!(wait_for_fetch(&agent.name, REPAIR_TIMEOUT_SECS));
    assert!(
        second.connections() > before,
        "traffic moved to the new proxy"
    );
}

#[test]
fn destroy_and_rename_leave_no_egress_residue() {
    let client = SERVER.client();
    let (mut agent, proxy) = proxied_agent(&client, "egress-residue");
    let old_name = agent.name.clone();
    let new_name = unique_agent("egress-renamed");
    drop(proxy);

    let returned = client.rename_agent(&old_name, &new_name).expect("rename");
    agent.name = returned.clone();
    assert!(
        docker_cmd(&["inspect", &sidecar_name(&old_name)]).is_err(),
        "old sidecar removed"
    );
    assert!(!agents_dir().join(format!("{old_name}.proxy")).exists());
    assert!(agents_dir().join(format!("{new_name}.proxy")).exists());

    client.destroy_agent(&new_name).expect("destroy");
    assert!(
        docker_cmd(&["inspect", &sidecar_name(&new_name)]).is_err(),
        "sidecar removed"
    );
    assert!(!agents_dir().join(format!("{new_name}.proxy")).exists());
    assert!(!agents_dir()
        .join(format!("{new_name}.egress.json"))
        .exists());
}
