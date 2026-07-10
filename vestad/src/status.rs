//! The daemon's status: held in memory and mirrored to `status.json`, rendered as
//! the startup banner. `status.json` is the single source the `vestad status` and
//! systemd-install CLI processes read to reproduce the exact banner — pid-gated so
//! they never show a dead daemon's state. This module owns the file path, its
//! format, and the banner rendering ("one owner per decision").

use crate::docker::AgentStatus;
use crate::paint;
use qrcode::{render::unicode, EcLevel, QrCode};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

// --- Banner rendering ---

const BANNER_ACCENT: &str = "38;2;231;186;140"; // light orange #e7ba8c (24-bit truecolor)
const BANNER_DIM: &str = "2";
const BANNER_MARGIN: usize = 3; // spaces between the border and content
const BANNER_LABEL_W: usize = 9; // config label column width
const BANNER_ART_W: usize = 46; // fixed width of every VESTA_ART line

const STATUS_FRESH_WAIT_MS: u64 = 5000; // longest we wait for a post-start status.json write
const STATUS_FRESH_POLL_INTERVAL_MS: u64 = 100;

/// "VESTA" in an ANSI-shadow block font. Every line is exactly BANNER_ART_W wide
/// (a unit test enforces this, since the box geometry centers on that width).
const VESTA_ART: [&str; 6] = [
    "██╗   ██╗ ███████╗ ███████╗ ████████╗  █████╗ ",
    "██║   ██║ ██╔════╝ ██╔════╝ ╚══██╔══╝ ██╔══██╗",
    "██║   ██║ █████╗   ███████╗    ██║    ███████║",
    "╚██╗ ██╔╝ ██╔══╝   ╚════██║    ██║    ██╔══██║",
    " ╚████╔╝  ███████╗ ███████║    ██║    ██║  ██║",
    "  ╚═══╝   ╚══════╝ ╚══════╝    ╚═╝    ╚═╝  ╚═╝",
];

/// One row of the startup box. Each variant knows its natural (uncolored) width
/// so the renderer can size the box and pad every line to a uniform interior.
enum BoxRow {
    Gap,
    Art(usize),         // index into VESTA_ART, centered, accent colour
    Center(String),     // centered dim text (e.g. the version subtitle)
    Raw(String),        // left-aligned uncoloured text (QR rows must stay scannable)
    Kv(String, String), // "label   value", left-aligned; labels longer than the fixed column widen it
    Value(String),      // a full-width left-aligned value (e.g. the api key)
    Rule(String),       // "── label ─────" section divider
}

impl BoxRow {
    /// Visible width of the row's content, ignoring borders and side margins.
    fn width(&self) -> usize {
        match self {
            BoxRow::Gap => 0,
            BoxRow::Art(_) => BANNER_ART_W,
            BoxRow::Center(s) | BoxRow::Raw(s) | BoxRow::Value(s) => s.chars().count(),
            BoxRow::Kv(label, value) => {
                label.chars().count().max(BANNER_LABEL_W) + value.chars().count()
            }
            BoxRow::Rule(label) => label.chars().count() + 5, // "── " + " ─"
        }
    }

    /// Render the content fitted to `inner` columns as one or more `(plain,
    /// shown)` lines — long values (links, api key, a long error) are hard-wrapped
    /// so the box never overflows a narrow terminal. `plain` drives padding math
    /// (no ANSI); `shown` is what prints (equal to `plain` when colour is off).
    fn render(&self, inner: usize) -> Vec<(String, String)> {
        let centered = |line: &str, code: Option<&str>| {
            let lead = " ".repeat(inner.saturating_sub(line.chars().count()) / 2);
            let shown = match code {
                Some(code) => paint(code, line),
                None => line.to_string(),
            };
            (format!("{lead}{line}"), format!("{lead}{shown}"))
        };
        match self {
            BoxRow::Gap => vec![(String::new(), String::new())],
            BoxRow::Art(idx) => {
                let art = VESTA_ART[*idx];
                // Can't shrink the art; drop it rather than overflow a tiny box.
                if art.chars().count() > inner {
                    Vec::new()
                } else {
                    vec![centered(art, Some(BANNER_ACCENT))]
                }
            }
            BoxRow::Center(text) => wrap_chars(text, inner)
                .iter()
                .map(|line| centered(line, Some(BANNER_DIM)))
                .collect(),
            BoxRow::Raw(text) => vec![(text.clone(), text.clone())],
            BoxRow::Kv(label, value) => {
                let label_w = label.chars().count().max(BANNER_LABEL_W);
                let label_col = format!("{:<width$}", label, width = label_w);
                let value_width = inner.saturating_sub(label_w).max(1);
                wrap_chars(value, value_width)
                    .into_iter()
                    .enumerate()
                    .map(|(line_no, chunk)| {
                        if line_no == 0 {
                            (
                                format!("{label_col}{chunk}"),
                                format!("{}{chunk}", paint(BANNER_DIM, &label_col)),
                            )
                        } else {
                            // continuation lines align under the value column
                            let pad = " ".repeat(label_w);
                            (format!("{pad}{chunk}"), format!("{pad}{chunk}"))
                        }
                    })
                    .collect()
            }
            BoxRow::Value(value) => wrap_chars(value, inner)
                .into_iter()
                .map(|chunk| (chunk.clone(), paint(BANNER_ACCENT, &chunk)))
                .collect(),
            BoxRow::Rule(label) => {
                let prefix = format!("── {} ", label);
                let fill = inner.saturating_sub(prefix.chars().count());
                let plain = format!("{}{}", prefix, "─".repeat(fill));
                vec![(plain.clone(), paint(BANNER_DIM, &plain))]
            }
        }
    }
}

/// Hard-wrap `text` into chunks of at most `width` characters (character-wise, so
/// unbreakable strings like URLs and keys still fit). Always returns ≥1 element.
fn wrap_chars(text: &str, width: usize) -> Vec<String> {
    if width == 0 || text.is_empty() {
        return vec![text.to_string()];
    }
    text.chars()
        .collect::<Vec<char>>()
        .chunks(width)
        .map(|chunk| chunk.iter().collect())
        .collect()
}

/// Terminal width (columns) of stderr, or `None` when it isn't a TTY / can't be
/// queried — callers fall back to a conservative default.
fn terminal_width() -> Option<usize> {
    use std::os::unix::io::AsRawFd;
    let mut size: libc::winsize = unsafe { std::mem::zeroed() };
    // SAFETY: TIOCGWINSZ fills the winsize through the pointer for a valid fd; we
    // pass stderr's fd and a correctly sized, zeroed struct.
    let rc = unsafe { libc::ioctl(std::io::stderr().as_raw_fd(), libc::TIOCGWINSZ, &mut size) };
    (rc == 0 && size.ws_col > 0).then_some(size.ws_col as usize)
}

/// Draw the rows inside a rounded, accent-coloured box. The interior is as wide
/// as the content but capped to the terminal so the box never wraps; over-long
/// rows are wrapped to fit. Returns the finished lines (plain when colour is off,
/// which is how the geometry test inspects them).
fn render_box(rows: &[BoxRow]) -> Vec<String> {
    // Reserve the 2-space outer indent, both borders, and both side margins.
    let overhead = 2 + 2 + BANNER_MARGIN * 2;
    let cap = terminal_width().unwrap_or(80).saturating_sub(overhead);
    render_box_capped(rows, cap)
}

/// [`render_box`] with the interior width cap passed explicitly (so the wrapping
/// behaviour is testable without a real terminal).
fn render_box_capped(rows: &[BoxRow], cap: usize) -> Vec<String> {
    let natural = rows.iter().map(BoxRow::width).max().unwrap_or(0);
    let inner = natural.min(cap).max(1);
    let span = BANNER_MARGIN * 2 + inner;
    let edge = |left: &str, right: &str| {
        format!(
            "{}{}{}",
            paint(BANNER_ACCENT, left),
            paint(BANNER_ACCENT, &"─".repeat(span)),
            paint(BANNER_ACCENT, right)
        )
    };
    let mut out = vec![edge("╭", "╮")];
    let side = paint(BANNER_ACCENT, "│");
    for row in rows {
        for (plain, shown) in row.render(inner) {
            let trailing = inner.saturating_sub(plain.chars().count());
            out.push(format!(
                "{side}{margin}{shown}{trailing}{margin}{side}",
                margin = " ".repeat(BANNER_MARGIN),
                trailing = " ".repeat(trailing),
            ));
        }
    }
    out.push(edge("╰", "╯"));
    out
}

/// First line of `msg`, trimmed and capped to `max` chars with an ellipsis, so a
/// long or multi-line error can't blow up the banner width.
fn first_line_truncated(msg: &str, max: usize) -> String {
    let line = msg.lines().next().unwrap_or(msg).trim();
    if line.chars().count() <= max {
        line.to_string()
    } else {
        format!(
            "{}…",
            line.chars().take(max.saturating_sub(1)).collect::<String>()
        )
    }
}

/// Build the app connect link: the app reads the key from the URL fragment
/// (`#k=...`), which browsers never send to the server, so the key stays out of
/// request logs.
fn connect_link(base_url: &str, api_key: &str) -> String {
    format!("{base_url}/app#k={api_key}")
}

/// Render `data` as a square QR using half-block glyphs (the densest *square*
/// terminal rendering: 1 module wide, 2 modules tall per cell). A light module is
/// drawn as a filled glyph and a dark module as empty, which on a dark terminal
/// (light foreground) yields a correct-polarity, scannable code; the quiet zone
/// is the bright border. Lowest error-correction (`L`) keeps it as small as a
/// square code gets. Empty on the rare encode failure.
fn qr_lines(data: &str) -> Vec<String> {
    let Ok(code) = QrCode::with_error_correction_level(data.as_bytes(), EcLevel::L) else {
        return Vec::new();
    };
    code.render::<unicode::Dense1x2>()
        .dark_color(unicode::Dense1x2::Light)
        .light_color(unicode::Dense1x2::Dark)
        .quiet_zone(true)
        .build()
        .lines()
        .map(str::to_string)
        .collect()
}

/// The `── agents (N) ──` section: one row per agent, name column padded so the
/// status column stays aligned even for names longer than the config label column.
fn agent_rows(agents: &[AgentEntry]) -> Vec<BoxRow> {
    let name_w = agents
        .iter()
        .map(|agent| agent.name.chars().count() + 2)
        .max()
        .unwrap_or(0)
        .max(BANNER_LABEL_W);
    let mut rows = vec![BoxRow::Rule(format!("agents ({})", agents.len()))];
    for agent in agents {
        let status_text = match agent.status {
            Some(status) => status.human_text(),
            None => "",
        };
        rows.push(BoxRow::Kv(
            format!("{:<name_w$}", agent.name),
            status_text.to_string(),
        ));
    }
    rows
}

// --- Status ---

/// How the Cloudflare tunnel stands, as surfaced in the banner. Held in memory by
/// the daemon and serialized into `status.json`.
#[derive(Serialize, Deserialize, Clone, PartialEq)]
pub enum TunnelStatus {
    Disabled,       // --no-tunnel
    Active(String), // reachable https URL
    Failed(String), // wanted, but couldn't be established — concise reason
}

impl TunnelStatus {
    pub fn url(&self) -> Option<&str> {
        match self {
            TunnelStatus::Active(url) => Some(url),
            _ => None,
        }
    }
}

/// One agent as shown in the banner: its name plus the daemon's last known status
/// (`None` at boot, before the status cache has polled the containers).
#[derive(Serialize, Deserialize, Clone, PartialEq)]
pub struct AgentEntry {
    pub name: String,
    pub status: Option<AgentStatus>,
}

/// The daemon's startup state. Every field except `tunnel` and `agents` is fixed
/// for the life of the process; `tunnel` is kept current by the supervisor and
/// `agents` by the agent-status cache task. `pid` lets readers of `status.json`
/// confirm the snapshot belongs to the live daemon.
#[derive(Serialize, Deserialize, Clone)]
pub struct Status {
    pub version: String,
    pub user: String,
    pub port: u16,
    pub dev_mode: bool,
    pub expose_lan: bool,
    pub lan_url: Option<String>,
    pub tunnel: TunnelStatus,
    #[serde(default)]
    pub agents: Vec<AgentEntry>,
    pub pid: u32,
}

impl Status {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        version: String,
        user: String,
        port: u16,
        dev_mode: bool,
        expose_lan: bool,
        lan_url: Option<String>,
        tunnel: TunnelStatus,
        agents: Vec<AgentEntry>,
    ) -> Self {
        Status {
            version,
            user,
            port,
            dev_mode,
            expose_lan,
            lan_url,
            tunnel,
            agents,
            pid: std::process::id(),
        }
    }

    /// Sole owner of the `status.json` path.
    fn path(config: &Path) -> PathBuf {
        config.join("status.json")
    }

    /// Atomically write `status.json` (tmp + rename). Best-effort: the file is
    /// re-derivable on the next boot, so a failure is logged, never fatal. Carries
    /// no secret (the api key stays in the `api-key` file).
    pub fn persist(&self, config: &Path) {
        let Ok(json) = serde_json::to_vec_pretty(self) else {
            return;
        };
        let path = Self::path(config);
        let tmp = path.with_extension("json.tmp");
        if std::fs::write(&tmp, json).is_ok() {
            if let Err(e) = std::fs::rename(&tmp, &path) {
                tracing::warn!("failed to persist status.json: {e}");
            }
        }
    }

    pub fn load(config: &Path) -> Option<Status> {
        let data = std::fs::read_to_string(Self::path(config)).ok()?;
        serde_json::from_str(&data).ok()
    }

    /// Poll for `status.json` to be (re)written at or after `since`. The systemd
    /// unit is not `Type=notify`, so the caller's "process is active" check only
    /// confirms the daemon launched, not that its async startup (tunnel dial,
    /// etc.) finished and persisted a fresh status. Gives up after
    /// `STATUS_FRESH_WAIT_MS`; the caller renders whatever `status.json` holds
    /// either way.
    pub fn wait_for_fresh(config: &Path, since: std::time::SystemTime) -> bool {
        let deadline =
            std::time::Instant::now() + std::time::Duration::from_millis(STATUS_FRESH_WAIT_MS);
        while std::time::Instant::now() < deadline {
            let fresh = std::fs::metadata(Self::path(config))
                .and_then(|metadata| metadata.modified())
                .is_ok_and(|modified| modified >= since);
            if fresh {
                return true;
            }
            std::thread::sleep(std::time::Duration::from_millis(
                STATUS_FRESH_POLL_INTERVAL_MS,
            ));
        }
        false
    }

    pub fn set_tunnel(&mut self, tunnel: TunnelStatus) {
        self.tunnel = tunnel;
    }

    pub fn set_agents(&mut self, agents: Vec<AgentEntry>) {
        self.agents = agents;
    }

    /// Print the boxed banner: VESTA art, config grid, connection summary, and the
    /// per-tier connect links (with a QR for the remote link). `api_key` is passed
    /// in rather than persisted, so the secret never lands in `status.json`.
    pub fn print_banner(&self, api_key: &str) {
        let local_url = format!("http://localhost:{}", self.port + 1);
        let tunnel_url = self.tunnel.url();

        // enabled = tunnel up; disabled = --no-tunnel; error: <reason> = a tunnel
        // was wanted but couldn't be established (no creds, dead tunnel, API error).
        let tunnel_desc = match &self.tunnel {
            TunnelStatus::Active(_) => "enabled".to_string(),
            TunnelStatus::Disabled => "disabled".to_string(),
            TunnelStatus::Failed(reason) => format!("error: {}", first_line_truncated(reason, 100)),
        };
        let lan_desc = if self.expose_lan {
            "enabled"
        } else {
            "disabled"
        }
        .to_string();
        let lan_url = self.lan_url.as_deref();
        // The address most useful to a human: public tunnel, else the LAN URL when
        // exposed, else the same-machine local URL.
        let address = tunnel_url
            .map(str::to_string)
            .or_else(|| lan_url.map(str::to_string))
            .unwrap_or_else(|| local_url.clone());
        // The LAN connect link is only real when the API is actually bound to the LAN.
        let lan_app = self.expose_lan.then_some(lan_url).flatten();

        let mut rows = vec![
            BoxRow::Gap,
            BoxRow::Art(0),
            BoxRow::Art(1),
            BoxRow::Art(2),
            BoxRow::Art(3),
            BoxRow::Art(4),
            BoxRow::Art(5),
            BoxRow::Gap,
            BoxRow::Center(format!("personal AI daemon · v{}", self.version)),
            BoxRow::Gap,
            BoxRow::Kv("user".into(), self.user.clone()),
            BoxRow::Kv("port".into(), self.port.to_string()),
            BoxRow::Kv(
                "mode".into(),
                if self.dev_mode {
                    "development".to_string()
                } else {
                    "production".to_string()
                },
            ),
            BoxRow::Kv("tunnel".into(), tunnel_desc),
            BoxRow::Kv("lan".into(), lan_desc),
            BoxRow::Gap,
        ];
        rows.extend(agent_rows(&self.agents));
        rows.extend([
            BoxRow::Gap,
            BoxRow::Rule("connection".into()),
            BoxRow::Kv("address".into(), address),
            BoxRow::Kv("api key".into(), api_key.to_string()),
            BoxRow::Gap,
            BoxRow::Rule("connect the app".into()),
        ]);
        // remote tier: the public link when a tunnel is up (with the QR for it
        // right beneath, left-aligned), otherwise how to get one.
        rows.push(BoxRow::Kv("remote".into(), String::new()));
        match tunnel_url {
            Some(url) => {
                let link = connect_link(url, api_key);
                rows.push(BoxRow::Value(link.clone()));
                rows.push(BoxRow::Gap);
                rows.extend(qr_lines(&link).into_iter().map(BoxRow::Raw));
            }
            None => rows.push(BoxRow::Value(
                "run `vestad connect` for a public URL".to_string(),
            )),
        }
        if let Some(url) = lan_app {
            rows.push(BoxRow::Gap);
            rows.push(BoxRow::Kv("lan".into(), String::new()));
            rows.push(BoxRow::Value(connect_link(url, api_key)));
        }
        rows.push(BoxRow::Gap);
        rows.push(BoxRow::Kv("local".into(), String::new()));
        rows.push(BoxRow::Value(connect_link(&local_url, api_key)));
        rows.push(BoxRow::Gap);

        eprintln!();
        for line in render_box(&rows) {
            eprintln!("  {line}");
        }
        eprintln!();
    }
}

/// Whether `pid` names a live process. Same-user `kill(pid, 0)` checks existence
/// without delivering a signal — enough to confirm a persisted `status.json`
/// belongs to the currently-running daemon (both run as the same user).
pub fn pid_is_live(pid: u32) -> bool {
    // SAFETY: signal 0 performs only existence/permission checks; nothing is sent.
    unsafe { libc::kill(pid as i32, 0) == 0 }
}

/// Render the banner from `status.json` for the `vestad status` / systemd-install
/// CLIs. Only renders when the persisted daemon pid is live, so a stale file from
/// a stopped or previous daemon never shows a misleading box.
pub fn print_status_banner(config: &Path, api_key: Option<&str>) {
    match Status::load(config) {
        Some(status) if pid_is_live(status.pid) => match api_key {
            Some(key) => status.print_banner(key),
            None => {
                eprintln!();
                eprintln!(
                    "  {}",
                    paint(BANNER_DIM, "vestad is running (api key unavailable)")
                );
                eprintln!();
            }
        },
        _ => {
            eprintln!();
            eprintln!("  {}", paint(BANNER_DIM, "vestad is not running"));
            eprintln!();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn vesta_art_lines_are_uniform_width() {
        for line in VESTA_ART {
            assert_eq!(line.chars().count(), BANNER_ART_W, "art line: {line}");
        }
    }

    #[test]
    fn render_box_lines_share_width_and_are_bordered() {
        // Colour is disabled under `cargo test` (stderr is not a TTY), so the
        // rendered lines are plain and char count equals display width.
        let rows = vec![
            BoxRow::Gap,
            BoxRow::Art(0),
            BoxRow::Center("personal AI daemon".into()),
            BoxRow::Kv("user".into(), "emi".into()),
            BoxRow::Rule("connection".into()),
            BoxRow::Value("0123456789abcdef0123456789abcdef".into()),
        ];
        let lines = render_box(&rows);
        let width = lines[0].chars().count();
        assert!(
            lines.iter().all(|l| l.chars().count() == width),
            "every box line is the same width"
        );
        assert!(lines.first().unwrap().starts_with('╭') && lines.first().unwrap().ends_with('╮'));
        assert!(lines.last().unwrap().starts_with('╰') && lines.last().unwrap().ends_with('╯'));
        for interior in &lines[1..lines.len() - 1] {
            assert!(
                interior.starts_with('│') && interior.ends_with('│'),
                "interior row is bordered: {interior}"
            );
        }
    }

    #[test]
    fn render_box_wraps_long_rows_within_a_narrow_cap() {
        let long = "x".repeat(120);
        let cap = 30;
        let lines = render_box_capped(&[BoxRow::Value(long), BoxRow::Art(0)], cap);
        let width = lines[0].chars().count();
        // Uniform width, and the whole box stays within the cap (+ borders/margins).
        assert!(
            lines.iter().all(|l| l.chars().count() == width),
            "every box line is the same width"
        );
        assert!(
            width <= cap + 2 + BANNER_MARGIN * 2,
            "box width {width} exceeds cap {cap}"
        );
        // The 120-char value wrapped across multiple interior lines instead of overflowing.
        let value_lines = lines.iter().filter(|l| l.contains('x')).count();
        assert!(
            value_lines >= 4,
            "expected the long value to wrap into >=4 lines, got {value_lines}"
        );
    }

    #[test]
    fn status_json_round_trips_all_tunnel_states() {
        for tunnel in [
            TunnelStatus::Disabled,
            TunnelStatus::Active("https://host.example/".into()),
            TunnelStatus::Failed("invalid token".into()),
        ] {
            let status = Status::new(
                "0.1.0".into(),
                "emi".into(),
                8080,
                true,
                false,
                None,
                tunnel.clone(),
                Vec::new(),
            );
            let json = serde_json::to_string(&status).expect("serialize");
            let back: Status = serde_json::from_str(&json).expect("deserialize");
            assert!(back.tunnel == tunnel);
            assert_eq!(back.port, 8080);
            assert_eq!(back.pid, status.pid);
        }
    }

    #[test]
    fn status_json_round_trips_agents() {
        let agents = vec![
            AgentEntry {
                name: "vesta".into(),
                status: Some(AgentStatus::Alive),
            },
            AgentEntry {
                name: "fresh".into(),
                status: None,
            },
        ];
        let status = Status::new(
            "0.1.0".into(),
            "emi".into(),
            8080,
            false,
            false,
            None,
            TunnelStatus::Disabled,
            agents.clone(),
        );
        let json = serde_json::to_string(&status).expect("serialize");
        let back: Status = serde_json::from_str(&json).expect("deserialize");
        assert!(back.agents == agents);
    }

    #[test]
    fn agent_section_renders_count_names_and_statuses() {
        let agents = vec![
            AgentEntry {
                name: "vesta".into(),
                status: Some(AgentStatus::Alive),
            },
            AgentEntry {
                name: "backup".into(),
                status: Some(AgentStatus::NotAuthenticated),
            },
        ];
        let text = render_box_capped(&agent_rows(&agents), 60).join("\n");
        assert!(text.contains("agents (2)"));
        assert!(text.contains("vesta"));
        assert!(text.contains("alive"));
        assert!(text.contains("backup"));
        assert!(text.contains("not authenticated"));
    }

    #[test]
    fn agent_section_without_statuses_shows_names_only() {
        let agents = vec![AgentEntry {
            name: "vesta".into(),
            status: None,
        }];
        let text = render_box_capped(&agent_rows(&agents), 60).join("\n");
        assert!(text.contains("agents (1)"));
        assert!(text.contains("vesta"));
    }

    #[test]
    fn agent_section_with_no_agents_renders_only_the_rule() {
        let lines = render_box_capped(&agent_rows(&[]), 60);
        assert!(lines.iter().any(|line| line.contains("agents (0)")));
        // top border + rule + bottom border: no agent rows
        assert_eq!(lines.len(), 3);
    }

    #[test]
    fn agent_names_longer_than_the_label_column_stay_separated_and_aligned() {
        let agents = vec![
            AgentEntry {
                name: "vesta".into(),
                status: Some(AgentStatus::Alive),
            },
            AgentEntry {
                name: "longagentname".into(),
                status: Some(AgentStatus::Stopped),
            },
        ];
        let lines = render_box_capped(&agent_rows(&agents), 60);
        let column_of = |needle: &str| {
            lines
                .iter()
                .find_map(|line| line.find(needle))
                .unwrap_or_else(|| panic!("no line contains {needle}"))
        };
        assert_eq!(
            column_of("alive"),
            column_of("stopped"),
            "status column is aligned across rows"
        );
        assert!(
            lines.iter().any(|line| line.contains("longagentname ")),
            "long name stays separated from its status"
        );
    }

    #[test]
    fn pid_liveness_detects_self_and_a_dead_pid() {
        assert!(pid_is_live(std::process::id()), "our own pid must be live");
        // i32::MAX is above the kernel pid_max, so it can never name a process.
        assert!(
            !pid_is_live(i32::MAX as u32),
            "a never-allocated pid must be dead"
        );
    }
}
