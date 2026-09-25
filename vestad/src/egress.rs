//! Per-agent egress through a proxy: the proxy URL, the sing-box config rendered from it, and
//! the host files that hold both. Decisions and file IO only: Docker lives in `docker.rs`, and
//! network IO lives in `egress_net.rs`.

use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};

const PROXY_FILE_SUFFIX: &str = "proxy";
const CONFIG_FILE_SUFFIX: &str = "egress.json";
const PRIVATE_FILE_MODE: u32 = 0o600;
const SIDECAR_PREFIX: &str = "vesta-egress-";
const PASSWORD_MASK: &str = "***";
const TUN_ADDRESS: &str = "198.18.0.1/30";
const TUN_MTU: u16 = 1500;
/// The DNS server the sidecar hands Docker's embedded resolver. A public address, so each
/// forwarded lookup enters the TUN and sing-box answers it through the proxy.
pub const SIDECAR_DNS: &str = "1.1.1.1";
/// Destinations that never enter the TUN: loopback plus every private and link-local range,
/// which is where vestad and the Docker networks live.
const DIRECT_RANGES: &[&str] = &[
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
];

#[derive(Debug)]
pub struct EgressError(String);

impl std::fmt::Display for EgressError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for EgressError {}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProxyScheme {
    Http,
    Socks5,
}

impl ProxyScheme {
    fn url_scheme(self) -> &'static str {
        match self {
            Self::Http => "http",
            Self::Socks5 => "socks5",
        }
    }
}

#[derive(Clone, PartialEq, Eq)]
pub struct ProxyUrl {
    scheme: ProxyScheme,
    host: String,
    port: u16,
    username: Option<String>,
    password: Option<String>,
    raw: String,
}

/// Prints only the masked form, never the password, so a stray `{proxy:?}` in a log line
/// cannot leak the credential.
impl std::fmt::Debug for ProxyUrl {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_tuple("ProxyUrl").field(&self.masked()).finish()
    }
}

impl ProxyUrl {
    pub fn parse(raw: &str) -> Result<Self, EgressError> {
        let raw = raw.trim();
        let url =
            reqwest::Url::parse(raw).map_err(|e| EgressError(format!("invalid proxy url: {e}")))?;
        let scheme = match url.scheme() {
            "http" => ProxyScheme::Http,
            "socks5" => ProxyScheme::Socks5,
            other => {
                return Err(EgressError(format!(
                    "unsupported proxy scheme '{other}': use http or socks5"
                )))
            }
        };
        let host = url
            .host_str()
            .map(|host| host.trim_start_matches('[').trim_end_matches(']'))
            .filter(|host| !host.is_empty())
            .ok_or_else(|| EgressError("proxy url has no host".to_string()))?
            .to_string();
        let port = url
            .port_or_known_default()
            .ok_or_else(|| EgressError("proxy url has no port".to_string()))?;
        let username = Some(url.username())
            .filter(|name| !name.is_empty())
            .map(percent_decode)
            .transpose()?;
        let password = url.password().map(percent_decode).transpose()?;
        Ok(Self {
            scheme,
            host,
            port,
            username,
            password,
            raw: raw.to_string(),
        })
    }

    pub fn raw(&self) -> &str {
        &self.raw
    }

    /// The URL with its password replaced, for every surface a person or a log reads.
    pub fn masked(&self) -> String {
        let host = if self.host.contains(':') {
            format!("[{}]", self.host)
        } else {
            self.host.clone()
        };
        let credentials = match (&self.username, &self.password) {
            (Some(user), Some(_)) => format!("{user}:{PASSWORD_MASK}@"),
            (Some(user), None) => format!("{user}@"),
            (None, _) => String::new(),
        };
        format!(
            "{}://{credentials}{host}:{}",
            self.scheme.url_scheme(),
            self.port
        )
    }

    pub fn sing_box_config(&self) -> serde_json::Value {
        let mut outbound = serde_json::Map::new();
        match self.scheme {
            ProxyScheme::Socks5 => {
                outbound.insert("type".into(), "socks".into());
                outbound.insert("version".into(), "5".into());
            }
            ProxyScheme::Http => {
                outbound.insert("type".into(), "http".into());
            }
        }
        outbound.insert("tag".into(), "proxy".into());
        outbound.insert("server".into(), self.host.clone().into());
        outbound.insert("server_port".into(), self.port.into());
        outbound.insert("domain_resolver".into(), "bootstrap".into());
        if let Some(user) = &self.username {
            outbound.insert("username".into(), user.clone().into());
        }
        if let Some(password) = &self.password {
            outbound.insert("password".into(), password.clone().into());
        }
        serde_json::json!({
            "log": {"level": "warn"},
            "dns": {
                "servers": [
                    // Over HTTPS, since a plain proxy may allow CONNECT to 443 only. Unverified:
                    // the sidecar image carries no CA bundle, only `/sing-box`, so a verified
                    // handshake to this hardcoded, well-known address fails closed on every
                    // lookup (`x509: certificate signed by unknown authority`); the actual
                    // traffic this resolves for still gets its own, ordinary TLS verification.
                    {"type": "https", "tag": "remote", "server": SIDECAR_DNS, "detour": "proxy", "tls": {"insecure": true}},
                    // No detour, so this leaves directly: only the lookup of the proxy's own
                    // hostname (`domain_resolver` on the outbound), never a forwarded query.
                    {"type": "udp", "tag": "bootstrap", "server": SIDECAR_DNS}
                ],
                "final": "remote"
            },
            "inbounds": [{
                "type": "tun",
                "tag": "tun-in",
                "interface_name": "tun0",
                "address": [TUN_ADDRESS],
                "mtu": TUN_MTU,
                "auto_route": true,
                "strict_route": true,
                "route_exclude_address": DIRECT_RANGES,
                "stack": "gvisor"
            }],
            "outbounds": [outbound],
            "route": {
                "rules": [{"action": "sniff"}, {"protocol": "dns", "action": "hijack-dns"}],
                "final": "proxy",
                "auto_detect_interface": true
            }
        })
    }
}

fn percent_decode(text: &str) -> Result<String, EgressError> {
    let invalid = || EgressError("invalid percent-encoding in proxy credentials".to_string());
    let bytes = text.as_bytes();
    let mut decoded = Vec::with_capacity(bytes.len());
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' {
            let pair = text.get(index + 1..index + 3).ok_or_else(invalid)?;
            decoded.push(u8::from_str_radix(pair, 16).map_err(|_| invalid())?);
            index += 3;
        } else {
            decoded.push(bytes[index]);
            index += 1;
        }
    }
    String::from_utf8(decoded).map_err(|_| invalid())
}

pub fn sidecar_name(agent: &str) -> String {
    format!("{SIDECAR_PREFIX}{}-{agent}", crate::paths::current_user())
}

fn agent_file(agents_dir: &Path, agent: &str, suffix: &str) -> PathBuf {
    agents_dir.join(format!("{agent}.{suffix}"))
}

/// Write `bytes` owner-only, through a temp file and a rename, so the file never exists with
/// looser permissions or half written.
fn write_private(path: &Path, bytes: &[u8]) -> Result<(), EgressError> {
    let fail = |e: std::io::Error| EgressError(format!("failed to write {}: {e}", path.display()));
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(fail)?;
    }
    let mut tmp = path.as_os_str().to_owned();
    tmp.push(".tmp");
    let tmp = PathBuf::from(tmp);
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(PRIVATE_FILE_MODE)
        .open(&tmp)
        .map_err(fail)?;
    file.write_all(bytes).map_err(fail)?;
    std::fs::rename(&tmp, path).map_err(fail)
}

pub fn load_proxy(agents_dir: &Path, agent: &str) -> Result<Option<ProxyUrl>, EgressError> {
    let path = agent_file(agents_dir, agent, PROXY_FILE_SUFFIX);
    match std::fs::read_to_string(&path) {
        Ok(raw) => ProxyUrl::parse(&raw).map(Some),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(EgressError(format!(
            "failed to read {}: {e}",
            path.display()
        ))),
    }
}

pub fn save_proxy(agents_dir: &Path, agent: &str, proxy: &ProxyUrl) -> Result<(), EgressError> {
    write_private(
        &agent_file(agents_dir, agent, PROXY_FILE_SUFFIX),
        proxy.raw().as_bytes(),
    )
}

pub fn delete_proxy(agents_dir: &Path, agent: &str) {
    std::fs::remove_file(agent_file(agents_dir, agent, PROXY_FILE_SUFFIX)).ok();
}

pub fn rename_proxy(agents_dir: &Path, old: &str, new: &str) -> Result<(), EgressError> {
    let from = agent_file(agents_dir, old, PROXY_FILE_SUFFIX);
    if !from.exists() {
        return Ok(());
    }
    std::fs::rename(&from, agent_file(agents_dir, new, PROXY_FILE_SUFFIX))
        .map_err(|e| EgressError(format!("failed to move {}: {e}", from.display())))
}

pub struct ConfigWrite {
    pub path: PathBuf,
    pub changed: bool,
}

pub fn write_config(
    agents_dir: &Path,
    agent: &str,
    proxy: &ProxyUrl,
) -> Result<ConfigWrite, EgressError> {
    let path = agent_file(agents_dir, agent, CONFIG_FILE_SUFFIX);
    let rendered = serde_json::to_vec_pretty(&proxy.sing_box_config())
        .map_err(|e| EgressError(format!("failed to render sing-box config: {e}")))?;
    let changed = std::fs::read(&path).ok().as_deref() != Some(rendered.as_slice());
    if changed {
        write_private(&path, &rendered)?;
    }
    Ok(ConfigWrite { path, changed })
}

pub fn delete_config(agents_dir: &Path, agent: &str) {
    std::fs::remove_file(agent_file(agents_dir, agent, CONFIG_FILE_SUFFIX)).ok();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_accepts_both_schemes_with_and_without_credentials() {
        let cases = [
            (
                "socks5://user:pass@gw.example.com:1080",
                ProxyScheme::Socks5,
                "gw.example.com",
                1080,
                Some("user"),
                Some("pass"),
            ),
            (
                "http://user:pass@1.2.3.4:8080",
                ProxyScheme::Http,
                "1.2.3.4",
                8080,
                Some("user"),
                Some("pass"),
            ),
            (
                "socks5://gw.example.com:1080",
                ProxyScheme::Socks5,
                "gw.example.com",
                1080,
                None,
                None,
            ),
            (
                "http://gw.example.com",
                ProxyScheme::Http,
                "gw.example.com",
                80,
                None,
                None,
            ),
            (
                "socks5://user@gw.example.com:1080",
                ProxyScheme::Socks5,
                "gw.example.com",
                1080,
                Some("user"),
                None,
            ),
        ];
        for (raw, scheme, host, port, username, password) in cases {
            let proxy = ProxyUrl::parse(raw).expect(raw);
            assert_eq!(proxy.scheme, scheme, "{raw}");
            assert_eq!(proxy.host, host, "{raw}");
            assert_eq!(proxy.port, port, "{raw}");
            assert_eq!(proxy.username.as_deref(), username, "{raw}");
            assert_eq!(proxy.password.as_deref(), password, "{raw}");
            assert_eq!(proxy.raw(), raw, "{raw}");
        }
    }

    #[test]
    fn parse_rejects_unusable_urls() {
        for raw in [
            "",
            "not a url",
            "https://gw.example.com:443",
            "socks4://gw.example.com:1080",
            "socks5://gw.example.com",
            "socks5://:1080",
            "socks5://user:%zz@gw.example.com:1080",
        ] {
            assert!(ProxyUrl::parse(raw).is_err(), "{raw} must be rejected");
        }
    }

    #[test]
    fn parse_decodes_percent_encoded_credentials() {
        let proxy =
            ProxyUrl::parse("socks5://us%40er:p%3Aa%2Fs%25s@gw.example.com:1080").expect("parse");
        assert_eq!(proxy.username.as_deref(), Some("us@er"));
        assert_eq!(proxy.password.as_deref(), Some("p:a/s%s"));
        assert_eq!(proxy.masked(), "socks5://us@er:***@gw.example.com:1080");
        let config = proxy.sing_box_config();
        assert_eq!(config["outbounds"][0]["username"], "us@er");
        assert_eq!(config["outbounds"][0]["password"], "p:a/s%s");
    }

    #[test]
    fn ipv6_host_loses_brackets_for_sing_box_and_keeps_them_for_display() {
        let proxy = ProxyUrl::parse("socks5://[2001:db8::1]:1080").expect("parse");
        assert_eq!(proxy.host, "2001:db8::1");
        assert_eq!(proxy.masked(), "socks5://[2001:db8::1]:1080");
        assert_eq!(
            proxy.sing_box_config()["outbounds"][0]["server"],
            "2001:db8::1"
        );
    }

    #[test]
    fn masked_hides_only_the_password() {
        let cases = [
            (
                "socks5://user:secret@gw.example.com:1080",
                "socks5://user:***@gw.example.com:1080",
            ),
            (
                "http://user@gw.example.com:8080",
                "http://user@gw.example.com:8080",
            ),
            ("http://gw.example.com:8080", "http://gw.example.com:8080"),
        ];
        for (raw, expected) in cases {
            let masked = ProxyUrl::parse(raw).expect(raw).masked();
            assert_eq!(masked, expected);
            assert!(!masked.contains("secret"));
        }
    }

    #[test]
    fn socks5_config_matches_the_verified_layout() {
        let proxy = ProxyUrl::parse("socks5://u:p@gw.example.com:1080").expect("parse");
        let expected = serde_json::json!({
            "log": {"level": "warn"},
            "dns": {
                "servers": [
                    {"type": "https", "tag": "remote", "server": "1.1.1.1", "detour": "proxy", "tls": {"insecure": true}},
                    {"type": "udp", "tag": "bootstrap", "server": "1.1.1.1"}
                ],
                "final": "remote"
            },
            "inbounds": [{
                "type": "tun",
                "tag": "tun-in",
                "interface_name": "tun0",
                "address": ["198.18.0.1/30"],
                "mtu": 1500,
                "auto_route": true,
                "strict_route": true,
                "route_exclude_address": [
                    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                    "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10"
                ],
                "stack": "gvisor"
            }],
            "outbounds": [{
                "type": "socks",
                "version": "5",
                "tag": "proxy",
                "server": "gw.example.com",
                "server_port": 1080,
                "domain_resolver": "bootstrap",
                "username": "u",
                "password": "p"
            }],
            "route": {
                "rules": [{"action": "sniff"}, {"protocol": "dns", "action": "hijack-dns"}],
                "final": "proxy",
                "auto_detect_interface": true
            }
        });
        assert_eq!(proxy.sing_box_config(), expected);
    }

    #[test]
    fn http_config_uses_an_http_outbound_without_credentials() {
        let proxy = ProxyUrl::parse("http://gw.example.com:8080").expect("parse");
        let expected = serde_json::json!({
            "type": "http",
            "tag": "proxy",
            "server": "gw.example.com",
            "server_port": 8080,
            "domain_resolver": "bootstrap"
        });
        assert_eq!(proxy.sing_box_config()["outbounds"][0], expected);
    }

    #[test]
    fn proxy_store_round_trips_and_is_owner_only() {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempfile::tempdir().expect("tempdir");
        assert_eq!(load_proxy(dir.path(), "bot").expect("load"), None);

        let proxy = ProxyUrl::parse("socks5://u:p@gw.example.com:1080").expect("parse");
        save_proxy(dir.path(), "bot", &proxy).expect("save");
        assert_eq!(
            load_proxy(dir.path(), "bot").expect("load"),
            Some(proxy.clone())
        );
        let mode = std::fs::metadata(dir.path().join("bot.proxy"))
            .expect("meta")
            .permissions()
            .mode();
        assert_eq!(mode & 0o777, 0o600);

        rename_proxy(dir.path(), "bot", "bot2").expect("rename");
        assert_eq!(load_proxy(dir.path(), "bot").expect("load"), None);
        assert_eq!(load_proxy(dir.path(), "bot2").expect("load"), Some(proxy));
        rename_proxy(dir.path(), "absent", "other").expect("renaming nothing is a no-op");

        delete_proxy(dir.path(), "bot2");
        delete_proxy(dir.path(), "bot2");
        assert_eq!(load_proxy(dir.path(), "bot2").expect("load"), None);
    }

    #[test]
    fn write_config_reports_whether_the_content_changed() {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempfile::tempdir().expect("tempdir");
        let first = ProxyUrl::parse("socks5://u:p@gw.example.com:1080").expect("parse");
        let second = ProxyUrl::parse("socks5://u:p@gw.example.com:1081").expect("parse");

        let written = write_config(dir.path(), "bot", &first).expect("write");
        assert!(written.changed);
        assert_eq!(written.path, dir.path().join("bot.egress.json"));
        let mode = std::fs::metadata(&written.path)
            .expect("meta")
            .permissions()
            .mode();
        assert_eq!(mode & 0o777, 0o600);
        assert!(
            !write_config(dir.path(), "bot", &first)
                .expect("rewrite")
                .changed
        );
        assert!(
            write_config(dir.path(), "bot", &second)
                .expect("change")
                .changed
        );

        delete_config(dir.path(), "bot");
        assert!(!written.path.exists());
    }

    #[test]
    fn debug_never_prints_the_password() {
        let proxy = ProxyUrl::parse("socks5://user:secret@gw.example.com:1080").expect("parse");
        let printed = format!("{proxy:?}");
        assert!(!printed.contains("secret"), "{printed}");
        assert!(printed.contains("***"), "{printed}");
    }

    #[test]
    fn sidecar_name_is_user_scoped() {
        let name = sidecar_name("bot");
        assert_eq!(
            name,
            format!("vesta-egress-{}-bot", crate::paths::current_user())
        );
    }
}
