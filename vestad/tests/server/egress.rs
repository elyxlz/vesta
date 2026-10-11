//! The per-agent egress proxy API end to end: vestad installs the sing-box image, checks the
//! proxy, moves the agent into its sidecar's namespace, and hides the password everywhere.
//! Needs Docker and internet (the sing-box download and the preflight to api.anthropic.com).
//!
//! Setting or clearing a proxy, a rename, and a restore each rebuild the agent container (a
//! `docker export | import` snapshot of a multi-GB image), so each test below walks as few
//! agents through as few rebuilds as possible rather than giving every behavior its own agent.
//! Every assertion still gets its own step, tagged in its failure message so a break says which
//! behavior broke.

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
    pub(crate) ip: String,
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
        let ip = Self::inspect_ip(agent, &container);
        wait_for_listener(&ip, TEST_PROXY_PORT);
        Self {
            container,
            url: format!("socks5://{TEST_PROXY_USER}:{TEST_PROXY_PASSWORD}@{ip}:{TEST_PROXY_PORT}"),
            ip,
            _config_dir: config_dir,
        }
    }

    fn inspect_ip(agent: &str, container: &str) -> String {
        let ip_format = format!(
            "{{{{(index .NetworkSettings.Networks \"{}\").IPAddress}}}}",
            agent_network(agent)
        );
        docker_cmd(&["inspect", "-f", &ip_format, container])
            .expect("proxy ip")
            .trim()
            .to_string()
    }

    /// A hostname that resolves, via sslip.io's public DNS, straight back to this proxy's own
    /// container IP: `a-b-c-d.sslip.io` maps to `a.b.c.d`. Used to prove the sidecar resolves the
    /// proxy's hostname itself rather than being handed a bare IP.
    pub(crate) fn sslip_hostname_url(&self) -> String {
        let hostname = self.ip.replace('.', "-");
        format!("socks5://{TEST_PROXY_USER}:{TEST_PROXY_PASSWORD}@{hostname}.sslip.io:{TEST_PROXY_PORT}")
    }

    /// Bring a stopped proxy back and wait for its listener, mirroring the wait `start` does.
    pub(crate) fn restart(&self) {
        docker_cmd(&["start", &self.container]).expect("restart test proxy");
        wait_for_listener(&self.ip, TEST_PROXY_PORT);
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

/// A loopback proxy URL: refused before the image install or the preflight, since the host's
/// loopback is never the sidecar's.
const LOOPBACK_PROXY: &str = "socks5://127.0.0.1:1080";

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

/// No proxy is ever stored against this agent, so none of these checks rebuild its container:
/// every refusal happens before `apply_proxy_change` runs.
#[test]
fn requests_refused_before_any_proxy_is_stored() {
    let client = SERVER.client();
    let agent = running_agent(&client, "egress-static");
    let cname = agent_container_name(&agent.name);
    let before = network_mode(&cname);

    // [bad scheme] an unsupported scheme is a bad request.
    let (status, _) = client
        .set_proxy(&agent.name, "https://gw.example.com:443")
        .expect("[bad scheme] request");
    assert_eq!(status, 400, "[bad scheme] unsupported scheme must be a 400");

    // [loopback] a loopback proxy is refused: the host reaches it, the sidecar never would.
    let (status, body) = client
        .set_proxy(&agent.name, LOOPBACK_PROXY)
        .expect("[loopback] request");
    assert_eq!(
        status, 422,
        "[loopback] a loopback proxy must be refused: {body}"
    );

    // [dead proxy] refused by the preflight; this PUT is also what installs the egress image,
    // since a loopback/scheme refusal above never reaches that step.
    let (status, body) = client
        .set_proxy(&agent.name, DEAD_PROXY)
        .expect("[dead proxy] request");
    assert_eq!(
        status, 422,
        "[dead proxy] an unreachable proxy must be refused: {body}"
    );
    assert!(
        !body.contains("dead-secret"),
        "[dead proxy] the error must not leak the password: {body}"
    );

    // [no residue] none of the refusals above touched the agent or persisted a proxy file.
    assert_eq!(
        network_mode(&cname),
        before,
        "[no residue] network mode must be untouched by any refusal"
    );
    assert!(
        !agents_dir().join(format!("{}.proxy", agent.name)).exists(),
        "[no residue] no .proxy file stored by any refusal"
    );

    // [agent token] the proxy routes are refused to the agent's own token.
    let token = client
        .read_agent_token(&agent.name)
        .expect("[agent token] agent token");
    let (status, _) = client
        .get_proxy_as(&agent.name, ProxyAuth::AgentToken(&token))
        .expect("[agent token] get");
    assert_eq!(
        status, 401,
        "[agent token] must be refused to the agent's own token"
    );

    // [unknown agent] clearing the proxy of an agent that does not exist is a 404.
    let (status, _) = client
        .clear_proxy_status(&unique_agent("egress-missing"))
        .expect("[unknown agent] delete");
    assert_eq!(status, 404, "[unknown agent] must be a 404");
}

/// One agent walked through its whole proxied life: set, mask, route traffic, resist an
/// interface-bound bypass, no-op re-set, change proxy by hostname with no rebuild, go dark when
/// the proxy stops, repair after the sidecar restarts, then clear. One rebuild to move the agent
/// into its sidecar (the first `set`) and one to move it back out (the final `clear`); everything
/// in between reuses that same sidecar.
#[test]
fn a_proxied_agent_through_its_whole_life() {
    let client = SERVER.client();
    let agent = running_agent(&client, "egress-life");
    install_egress_image(&client, &agent.name);
    let cname = agent_container_name(&agent.name);
    let proxy_a = TestProxy::start(&agent.name);

    // [set] masks the password and moves the agent into its sidecar.
    let (status, body) = client
        .set_proxy(&agent.name, &proxy_a.url)
        .expect("[set] request");
    assert_eq!(status, 200, "[set] {body}");
    assert!(
        !body.contains(TEST_PROXY_PASSWORD),
        "[set] response must not leak the password: {body}"
    );
    assert!(
        body.contains("***"),
        "[set] response must mask the password: {body}"
    );

    // [get] reads back masked too.
    let (status, body) = client
        .get_proxy_as(&agent.name, ProxyAuth::ApiKey)
        .expect("[get] request");
    assert_eq!(status, 200, "[get] {body}");
    assert!(
        !body.contains(TEST_PROXY_PASSWORD),
        "[get] response must not leak the password: {body}"
    );
    assert!(
        body.contains(TEST_PROXY_USER),
        "[get] response must name the user: {body}"
    );

    let sidecar_id = docker_cmd(&["inspect", "-f", "{{.Id}}", &sidecar_name(&agent.name)])
        .expect("[set] sidecar exists")
        .trim()
        .to_string();
    assert_eq!(
        network_mode(&cname),
        format!("container:{sidecar_id}"),
        "[set] agent must move into the sidecar's namespace"
    );
    client
        .wait_until_running(&agent.name, AGENT_RUNNING_TIMEOUT_SECS)
        .expect("[set] agent running on its sidecar");

    // [traffic] ordinary requests leave through the proxy.
    let before = proxy_a.connections();
    assert!(
        wait_for_fetch(&agent.name, REQUEST_TIMEOUT_SECS * 2),
        "[traffic] the agent must reach the internet"
    );
    assert!(
        proxy_a.connections() > before,
        "[traffic] the request must have gone through the proxy"
    );

    // [vestad direct] the agent still reaches vestad itself, never through the proxy.
    let code = exec_in_container(
        &cname,
        ". /run/vestad-env && curl -sk -m 10 -o /dev/null -w '%{http_code}' https://$BOX_HOST:$VESTAD_PORT/health",
    )
    .expect("[vestad direct] reach vestad");
    assert_eq!(
        code.trim(),
        "200",
        "[vestad direct] vestad must be reachable directly"
    );

    // [interface bind] (C1) a socket bound straight to eth0 (`SO_BINDTODEVICE`, which `curl
    // --interface` and this UDP probe both use) must not skip sing-box's TUN rules, for TCP or
    // UDP, while the proxy is up.
    let eth0_tcp = || exec_in_container(&cname, "curl --interface eth0 -m 8 https://1.1.1.1/");
    assert!(
        eth0_tcp().is_err(),
        "[interface bind] an eth0-bound TCP connection must not reach the internet directly (proxy up)"
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
    let result = exec_in_container(&cname, udp_probe).expect("[interface bind] udp probe ran");
    assert_eq!(
        result.trim(),
        "blocked",
        "[interface bind] an eth0-bound UDP socket must not reach the internet directly (proxy up)"
    );

    // [idempotent set] the same URL again changes nothing, so the agent must not restart.
    let started_before = started_at(&cname);
    let (status, _) = client
        .set_proxy(&agent.name, &proxy_a.url)
        .expect("[idempotent set] request");
    assert_eq!(status, 200, "[idempotent set] repeating the same url");
    assert_eq!(
        started_at(&cname),
        started_before,
        "[idempotent set] the agent must not restart"
    );

    // [url change] a second proxy, given by an sslip.io hostname, keeps the same sidecar (no
    // rebuild) and moves traffic to it: covers both the url-change and the hostname-resolve
    // behaviors in one step.
    let proxy_b = TestProxy::start_named(&agent.name, "b");
    let (status, body) = client
        .set_proxy(&agent.name, &proxy_b.sslip_hostname_url())
        .expect("[url change] request");
    assert_eq!(status, 200, "[url change] {body}");
    let sidecar_after = docker_cmd(&["inspect", "-f", "{{.Id}}", &sidecar_name(&agent.name)])
        .expect("[url change] sidecar")
        .trim()
        .to_string();
    assert_eq!(
        sidecar_id, sidecar_after,
        "[url change] a url change must keep the sidecar"
    );
    let before = proxy_b.connections();
    assert!(
        wait_for_fetch(&agent.name, REPAIR_TIMEOUT_SECS),
        "[url change] the agent must reach the internet through the new proxy"
    );
    assert!(
        proxy_b.connections() > before,
        "[url change] traffic must have moved to the new proxy, resolved by its sslip.io hostname"
    );

    // [proxy stopped] stopping the active proxy blocks traffic instead of going direct, and an
    // eth0-bound request still fails.
    docker_cmd(&["stop", &proxy_b.container]).expect("[proxy stopped] stop proxy");
    let result = agent_fetch(&agent.name);
    assert!(
        !result.is_ok_and(|code| code.trim() == "200"),
        "[proxy stopped] with the proxy down, the request must fail"
    );
    assert!(
        eth0_tcp().is_err(),
        "[proxy stopped] an eth0-bound TCP connection must not reach the internet directly (proxy stopped)"
    );

    // [repair] a restarted sidecar brings the agent back online, once its proxy is back up too.
    // The repair must also drop the cached bridge IP, or a resolve that hit before the sidecar's
    // restart keeps the tap dialing the dead address and the roster never converges past Starting.
    proxy_b.restart();
    docker_cmd(&["restart", &sidecar_name(&agent.name)]).expect("[repair] restart sidecar");
    assert!(
        wait_for_fetch(&agent.name, REPAIR_TIMEOUT_SECS),
        "[repair] vestad must restart the agent into the sidecar's new namespace"
    );
    client
        .wait_until_running(&agent.name, AGENT_RUNNING_TIMEOUT_SECS)
        .expect("[repair] agent status must converge to running after the repair restart");

    // [clear] deletes the proxy, returning the agent to its own network and removing the sidecar.
    client.clear_proxy(&agent.name).expect("[clear] delete");
    assert_eq!(
        network_mode(&cname),
        agent_network(&agent.name),
        "[clear] agent must return to its own network"
    );
    assert!(
        docker_cmd(&["inspect", &sidecar_name(&agent.name)]).is_err(),
        "[clear] sidecar must be removed"
    );
    let (_, body) = client
        .get_proxy_as(&agent.name, ProxyAuth::ApiKey)
        .expect("[clear] get");
    assert_eq!(
        body.trim(),
        r#"{"url":null}"#,
        "[clear] proxy must read back as null"
    );
}

/// A stopped agent takes a proxy without waking up, then that same agent is renamed and
/// destroyed, proving both leave no egress residue behind. One rebuild (the `set` while stopped)
/// plus the rename's own snapshot; no traffic is exercised, so no running sidecar is needed.
#[test]
fn a_stopped_agent_through_a_proxy_change_rename_and_destroy() {
    let client = SERVER.client();
    let mut agent = running_agent(&client, "egress-stopped");
    install_egress_image(&client, &agent.name);
    let proxy = TestProxy::start(&agent.name);
    client.stop_agent(&agent.name).expect("[stop] stop");
    client
        .wait_until_stopped(&agent.name, AGENT_RUNNING_TIMEOUT_SECS)
        .expect("[stop] agent must reach stopped");

    // [set while stopped] a stopped agent stays stopped through a proxy change, and still gets
    // the container: layout.
    let (status, body) = client
        .set_proxy(&agent.name, &proxy.url)
        .expect("[set while stopped] request");
    assert_eq!(status, 200, "[set while stopped] {body}");
    assert_eq!(
        client
            .agent_status(&agent.name)
            .expect("[set while stopped] status")
            .status,
        "stopped",
        "[set while stopped] the agent must stay stopped"
    );
    assert!(
        network_mode(&agent_container_name(&agent.name)).starts_with("container:"),
        "[set while stopped] agent must get the sidecar's container: layout"
    );

    // The rename/destroy flow below never checks live traffic, so the test proxy's job is done.
    drop(proxy);

    // [rename] the old sidecar is gone and the `.proxy` file moves with the agent.
    let old_name = agent.name.clone();
    let new_name = unique_agent("egress-renamed");
    let returned = client
        .rename_agent(&old_name, &new_name)
        .expect("[rename] rename");
    agent.name = returned.clone();
    assert!(
        docker_cmd(&["inspect", &sidecar_name(&old_name)]).is_err(),
        "[rename] old sidecar must be removed"
    );
    assert!(
        !agents_dir().join(format!("{old_name}.proxy")).exists(),
        "[rename] old .proxy file must be gone"
    );
    assert!(
        agents_dir().join(format!("{new_name}.proxy")).exists(),
        "[rename] new .proxy file must exist"
    );

    // [destroy] the sidecar and both proxy files are gone.
    client.destroy_agent(&new_name).expect("[destroy] destroy");
    assert!(
        docker_cmd(&["inspect", &sidecar_name(&new_name)]).is_err(),
        "[destroy] sidecar must be removed"
    );
    assert!(
        !agents_dir().join(format!("{new_name}.proxy")).exists(),
        "[destroy] .proxy file must be gone"
    );
    assert!(
        !agents_dir()
            .join(format!("{new_name}.egress.json"))
            .exists(),
        "[destroy] egress config file must be gone"
    );
}
