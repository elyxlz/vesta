//! The gateway self-update, end to end, as real processes: a vestad started here resolves a release
//! from a local fake of the release source (`VESTAD_RELEASES_BASE_URL`), snapshots its agents, swaps
//! its own binary, and the next boot recovers whatever the previous one left behind.
//!
//! Two seams make that possible without touching production behavior. The release source defaults to
//! GitHub and is only redirected by the env var above. The version a binary reports for update
//! decisions is `option_env!("VESTAD_VERSION_OVERRIDE")`, compile-time and unset in every published
//! build, which is what lets the suite build a vestad that genuinely IS 99.0.0 (`build_vestad_with_version`)
//! and assert the updated boot reads its own ledger as landed rather than interrupted.
//!
//! The daemon under test is a debug binary, which is dev mode, and dev mode refuses `POST
//! /gateway/update`. `VESTAD_DEV=0` turns it off; a release build sets nothing and is unaffected.
//! A `systemctl` stub on PATH stands in for the unit: it reports the service active and records the
//! restart, and the test drives the relaunch itself (exactly as the upgrade e2e does), which also
//! keeps a test daemon from ever reaching the host's real vestad unit.

use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::LazyLock;
use std::time::{Duration, Instant};

use vesta_tests::client::{Client, SyncSocket};
use vesta_tests::release_server::{
    build_vestad_with_version, release_archive_bytes, ArtifactMode, FakeReleaseServer,
};
use vesta_tests::{docker_cmd, find_vestad, TestServer, TestServerBuilder, SERVER};

/// The release the fake source offers: far enough ahead that no real version can overtake it.
const NEWER_VERSION: &str = "99.0.0";
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(20);
/// Budget for one phase to arrive. Generous: the snapshot phase talks to Docker per agent, and the
/// apply phase downloads and unpacks a whole debug binary.
const PHASE_TIMEOUT: Duration = Duration::from_secs(180);
/// Budget for a file (the ledger, a swept container) to reach its expected state.
const SETTLE_TIMEOUT: Duration = Duration::from_secs(120);
const POLL_INTERVAL: Duration = Duration::from_millis(200);
/// The reconnect grace window every gateway here runs with (production is 30s). Long enough that the
/// test's socket is always connected before it expires, short enough not to pad the suite.
const ANNOUNCE_GRACE_SECS: u64 = 10;
/// The boot settle the maintenance-update test runs with (production is 60s). Comfortably longer
/// than the handshake plus the one `/version` read the test does before it offers the newer release,
/// so the window never fires while the release is still hidden.
const MAINTENANCE_SETTLE_SECS: u64 = 12;

static GATEWAY_COUNTER: AtomicU32 = AtomicU32::new(0);

/// The newer release, built once per test process: a full first build takes minutes, and two tests
/// install it. Cached in the workspace target dir, so later runs are incremental.
static NEWER_RELEASE_ARCHIVE: LazyLock<Result<Vec<u8>, String>> = LazyLock::new(|| {
    let binary = build_vestad_with_version(NEWER_VERSION)?;
    release_archive_bytes(&binary)
});

/// Containers and networks a previous run's gateway left behind when a test panicked before its own
/// cleanup. They carry a `gwupd<pid>` user the shared harness's sweep deliberately ignores, so this
/// suite owns its hygiene; a Docker host runs out of network address pools long before it runs out
/// of anything else. Once per process, and never this process's own.
static STALE_GATEWAYS_SWEPT: LazyLock<()> = LazyLock::new(|| {
    let mine = format!("gwupd{}-", std::process::id());
    let listings = [
        (vec!["ps", "-a", "--filter", "name=gwupd", "--format", "{{.Names}}"], vec!["rm", "-f"]),
        (vec!["network", "ls", "--filter", "name=gwupd", "--format", "{{.Name}}"], vec!["network", "rm"]),
    ];
    for (list, remove) in listings {
        let Ok(found) = docker_cmd(&list) else { continue };
        for name in found.lines().map(str::trim) {
            if name.is_empty() || name.contains(&mine) {
                continue;
            }
            let mut args = remove.clone();
            args.push(name);
            let _ = docker_cmd(&args);
        }
    }
});

fn newer_release_archive() -> Vec<u8> {
    match &*NEWER_RELEASE_ARCHIVE {
        Ok(bytes) => bytes.clone(),
        Err(error) => panic!("could not build the v{NEWER_VERSION} release: {error}"),
    }
}

// ── The gateway under test ──────────────────────────────────────

/// One installed gateway: its own HOME, the binary file the update replaces, and a `systemctl` stub.
/// Everything lives under the cargo target tmpdir rather than `/tmp`, because the shared harness's
/// orphan sweep kills any vestad whose HOME is a `/tmp` path.
struct Gateway {
    _tmp: tempfile::TempDir,
    home: PathBuf,
    user: String,
    installed: PathBuf,
    path: String,
    systemctl_log: PathBuf,
    settle_secs: Option<u64>,
}

impl Gateway {
    fn install(label: &str) -> Self {
        // The shared harness kills every vestad with a temp-looking HOME once, when its SERVER first
        // initializes. Force that to happen before this gateway exists, whichever test runs first.
        LazyLock::force(&SERVER);
        LazyLock::force(&STALE_GATEWAYS_SWEPT);
        let tmp = tempfile::TempDir::new_in(env!("CARGO_TARGET_TMPDIR")).expect("gateway tmpdir");
        let home = tmp.path().join("home");
        std::fs::create_dir_all(&home).expect("gateway home");
        let bin_dir = tmp.path().join("bin");
        std::fs::create_dir_all(&bin_dir).expect("gateway bin dir");

        // The installed binary is a COPY: the update replaces this exact file, so the checkout's
        // build is never touched.
        let installed = bin_dir.join("vestad");
        std::fs::copy(find_vestad().expect("locate the built vestad"), &installed)
            .expect("install vestad");
        make_executable(&installed);

        let systemctl_log = tmp.path().join("systemctl.log");
        write_systemctl_stub(&bin_dir.join("systemctl"), &systemctl_log);

        // The maintenance cycle would apply the fake release on its own if a run landed in the
        // 4-5am window, so this gateway only ever updates when the test asks it to.
        let config_dir = home.join(".config/vesta/vestad");
        std::fs::create_dir_all(&config_dir).expect("gateway config dir");
        std::fs::write(config_dir.join("settings.json"), r#"{"auto_update": false}"#)
            .expect("write settings");

        let inherited = std::env::var("PATH").unwrap_or_default();
        let id = GATEWAY_COUNTER.fetch_add(1, Ordering::SeqCst);
        Self {
            home,
            // Neither a `-t<digits>` nor a `test-e2e-` name, so the shared harness's container
            // sweep leaves this gateway's agents to the test's own cleanup.
            user: format!("gwupd{}-{label}-{id}", std::process::id()),
            installed,
            path: format!("{}:{inherited}", bin_dir.display()),
            systemctl_log,
            settle_secs: None,
            _tmp: tmp,
        }
    }

    /// Let the maintenance cycle apply a pending release on its own, instead of only when the test
    /// POSTs an update. Rewrites the settings this gateway booted with.
    fn with_auto_update(self, on: bool) -> Self {
        let config_dir = self.home.join(".config/vesta/vestad");
        std::fs::write(
            config_dir.join("settings.json"),
            format!(r#"{{"auto_update": {on}}}"#),
        )
        .expect("write settings");
        self
    }

    /// Shorten the boot settle before the first maintenance decision, so the window fires seconds
    /// after boot rather than the production minute.
    fn with_settle_secs(mut self, secs: u64) -> Self {
        self.settle_secs = Some(secs);
        self
    }

    /// Boot this gateway against `releases_base_url`. Every start is the same installed file, so a
    /// relaunch after an update runs whatever the update put there.
    fn start(&self, releases_base_url: &str) -> TestServer {
        let mut builder = TestServerBuilder::new()
            .user(&self.user)
            .home(self.home.clone())
            .vestad_bin(self.installed.clone())
            .env("VESTAD_RELEASES_BASE_URL", releases_base_url)
            .env("VESTAD_DEV", "0")
            .env(
                "VESTAD_UPDATE_ANNOUNCE_GRACE_SECS",
                &ANNOUNCE_GRACE_SECS.to_string(),
            )
            .env("PATH", &self.path);
        if let Some(secs) = self.settle_secs {
            builder = builder.env("VESTAD_MAINTENANCE_SETTLE_SECS", &secs.to_string());
        }
        builder.start().expect("start the gateway under test")
    }

    fn ledger(&self) -> Option<serde_json::Value> {
        let raw = std::fs::read_to_string(
            self.home.join(".config/vesta/vestad/update.json"),
        )
        .ok()?;
        serde_json::from_str(&raw).ok()
    }

    /// The step the ledger records. The ledger carries the whole phase, which is internally tagged,
    /// so the step name is the nested object's own `phase`.
    fn ledger_phase(&self) -> Option<String> {
        Some(self.ledger()?["phase"]["phase"].as_str()?.to_string())
    }

    fn restart_was_requested(&self) -> bool {
        std::fs::read_to_string(&self.systemctl_log)
            .is_ok_and(|log| log.lines().any(|line| line.contains("restart")))
    }

    fn container_name(&self, agent: &str) -> String {
        format!("vesta-{}-{}", self.user, agent)
    }

}

/// Create one agent for the snapshot phase to name. It is never started: the phase reports every
/// agent the gateway owns, and a container this young is below the backup age floor, so the pass
/// names it and skips the export.
fn create_agent(client: &Client, name: &str) -> String {
    client.create_agent(name).expect("create agent")
}

fn destroy_agent(client: &Client, name: &str) {
    let _ = client.stop_agent(name);
    let _ = client.destroy_agent(name);
}

fn make_executable(path: &Path) {
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o755))
        .expect("make the file executable");
}

/// A `systemctl` that reports the vestad unit active and records every call. `is_active` deciding
/// true is what makes the daemon walk the `Restarting` phase and leave the ledger a real systemd
/// restart would leave.
fn write_systemctl_stub(path: &Path, log: &Path) {
    let script = format!(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> {}\nexit 0\n",
        log.display()
    );
    let mut file = std::fs::File::create(path).expect("create the systemctl stub");
    file.write_all(script.as_bytes())
        .expect("write the systemctl stub");
    drop(file);
    make_executable(path);
}

// ── Reading the gateway operation off /sync ─────────────────────

/// Read the mandatory hello then the snapshot, returning both.
async fn handshake(sock: &mut SyncSocket) -> (serde_json::Value, serde_json::Value) {
    let hello = sock.recv_frame(HANDSHAKE_TIMEOUT).await.expect("hello frame");
    assert_eq!(hello["type"].as_str(), Some("hello"), "first frame is hello");
    let snapshot = sock
        .recv_frame(HANDSHAKE_TIMEOUT)
        .await
        .expect("snapshot frame");
    assert_eq!(
        snapshot["type"].as_str(),
        Some("snapshot"),
        "second frame is snapshot"
    );
    (hello, snapshot)
}

/// The gateway branch of any frame that carries one (the snapshot's tree, or a `state` delta).
fn gateway_of(frame: &serde_json::Value) -> &serde_json::Value {
    match frame["type"].as_str() {
        Some("snapshot") => &frame["tree"]["gateway"],
        _ => &frame["value"],
    }
}

/// Read `state` deltas until the gateway operation reaches `phase`, collecting every operation the
/// gateway projected on the way. Consecutive phase transitions can coalesce into one frame (the
/// projection is a watch, not a queue), so the walk is asserted as an ordered subsequence.
async fn collect_until_phase(
    sock: &mut SyncSocket,
    phase: &str,
) -> Result<Vec<serde_json::Value>, String> {
    let mut seen: Vec<serde_json::Value> = Vec::new();
    let deadline = Instant::now() + PHASE_TIMEOUT;
    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err(format!("never reached phase {phase}; saw {seen:?}"));
        }
        let frame = sock.recv_frame(remaining).await?;
        if frame["type"].as_str() != Some("state") {
            continue;
        }
        let operation = gateway_of(&frame)["operation"].clone();
        if operation.is_null() {
            continue;
        }
        // A retried update watches a socket whose projection still carries the prior attempt's
        // terminal `failed`. That residual precedes the fresh walk, so drop it while nothing else
        // has been seen: a terminal state never opens a forward walk, and counting it would read as
        // the update going backwards. A walk deliberately ending on `failed` keeps it.
        if seen.is_empty() && operation["phase"].as_str() == Some("failed") && phase != "failed" {
            continue;
        }
        let reached = operation["phase"].as_str() == Some(phase);
        seen.push(operation);
        if reached {
            return Ok(seen);
        }
    }
}

/// The rank of a phase in the one order an update walks, for asserting the observed subsequence
/// never goes backwards.
fn phase_rank(operation: &serde_json::Value) -> usize {
    match operation["phase"].as_str() {
        Some("snapshotting") => 0,
        Some("applying") => 1,
        Some("restarting") => 2,
        _ => 3,
    }
}

fn assert_phases_in_order(operations: &[serde_json::Value], target_version: &str) {
    let mut rank = 0;
    for operation in operations {
        assert_eq!(
            operation["kind"].as_str(),
            Some("update"),
            "every projected phase belongs to the update"
        );
        assert_eq!(
            operation["targetVersion"].as_str(),
            Some(target_version),
            "every phase names the release being installed"
        );
        let next = phase_rank(operation);
        assert!(
            next >= rank,
            "the update walked backwards: {operations:?}"
        );
        rank = next;
    }
}

// ── Polling helpers ─────────────────────────────────────────────

fn wait_until<T>(what: &str, mut probe: impl FnMut() -> Option<T>) -> T {
    let deadline = Instant::now() + SETTLE_TIMEOUT;
    loop {
        if let Some(value) = probe() {
            return value;
        }
        assert!(Instant::now() < deadline, "timed out waiting for {what}");
        std::thread::sleep(POLL_INTERVAL);
    }
}

fn container_exists(name: &str) -> bool {
    docker_cmd(&["ps", "-a", "--filter", &format!("name=^{name}$"), "--format", "{{.Names}}"])
        .is_ok_and(|out| out.lines().any(|line| line.trim() == name))
}

/// A leftover from a backup that was killed with its daemon: the throwaway container an export
/// leaves behind, named after the agent, which every boot sweeps.
fn plant_backup_leftover(gateway: &Gateway, agent: &str) -> String {
    let container = gateway.container_name(agent);
    let image = docker_cmd(&["inspect", "--format", "{{.Config.Image}}", &container])
        .expect("read the agent's image");
    let leftover = format!("vesta-backup-tmp-{agent}");
    let _ = docker_cmd(&["rm", "-f", &leftover]);
    docker_cmd(&["create", "--name", &leftover, &image, "true"]).expect("plant the leftover");
    leftover
}

// ── The scenarios ───────────────────────────────────────────────

/// The whole successful update: the phases every client watches, the binary really swapped, and the
/// next boot reading its own ledger as the update landing.
#[tokio::test]
async fn an_update_walks_its_phases_and_the_next_boot_reports_the_new_version() {
    let releases = FakeReleaseServer::start(NEWER_VERSION, ArtifactMode::Serve(newer_release_archive()))
        .expect("start the fake release source");
    let gateway = Gateway::install("ok");
    let server = gateway.start(releases.base_url());
    let client = server.client();
    let agent = create_agent(&client, "updated");

    let mut sock = client.open_sync().await.expect("open /sync");
    let (hello, snapshot) = handshake(&mut sock).await;
    assert_eq!(
        hello["version"].as_str(),
        Some(env!("CARGO_PKG_VERSION")),
        "the gateway starts as this build"
    );
    assert!(
        gateway_of(&snapshot)["operation"].is_null(),
        "an idle gateway projects no operation"
    );

    let (status, body) = client.start_gateway_update().expect("POST /gateway/update");
    assert_eq!(status, 202, "the update is accepted, not finished: {body}");
    assert_eq!(body["target_version"].as_str(), Some(NEWER_VERSION));

    let operations = collect_until_phase(&mut sock, "restarting")
        .await
        .expect("the update reaches the restart");
    assert_phases_in_order(&operations, NEWER_VERSION);
    let snapshotting: Vec<&serde_json::Value> = operations
        .iter()
        .filter(|operation| operation["phase"].as_str() == Some("snapshotting"))
        .collect();
    assert!(
        snapshotting
            .iter()
            .any(|operation| operation["agent"].as_str() == Some(agent.as_str())),
        "the snapshot phase names the agent it is backing up: {operations:?}"
    );
    assert!(
        operations
            .iter()
            .any(|operation| operation["phase"].as_str() == Some("applying")),
        "the update projects the install: {operations:?}"
    );
    // The projection leads the two durable effects (the ledger write, then the restart call), so
    // each is polled rather than read the instant its phase shows up.
    wait_until("the service restart to be requested", || {
        gateway.restart_was_requested().then_some(())
    });
    // The ledger the restart hands to the next boot: the release that is now on disk.
    wait_until("the restarting ledger", || {
        (gateway.ledger_phase().as_deref() == Some("restarting")).then_some(())
    });
    let ledger = gateway.ledger().expect("a restarting update leaves its ledger");
    assert_eq!(ledger["target_version"].as_str(), Some(NEWER_VERSION));

    // systemd would stop this process and start the swapped binary; without it, the test does.
    drop(sock);
    drop(client);
    drop(server);
    let updated_server = gateway.start(releases.base_url());
    let updated_client = updated_server.client();

    let mut sock = updated_client.open_sync().await.expect("reopen /sync");
    let (hello, snapshot) = handshake(&mut sock).await;
    assert_eq!(
        hello["version"].as_str(),
        Some(NEWER_VERSION),
        "the swapped binary is the release the update installed"
    );
    assert!(
        gateway_of(&snapshot)["operation"].is_null(),
        "an update that landed leaves nothing to watch"
    );
    assert_eq!(gateway.ledger(), None, "boot recovery clears the ledger");
    assert_eq!(
        updated_client.gateway_version().expect("GET /version")["version"].as_str(),
        Some(NEWER_VERSION)
    );

    // This socket never reported focus, so nobody watched the update land: once the grace window
    // closes the gateway announces it, which is the only signal an unattended client ever gets.
    let announcement = sock
        .expect_frame_matching(
            |frame| frame["type"].as_str() == Some("user_notification"),
            Duration::from_secs(ANNOUNCE_GRACE_SECS) + PHASE_TIMEOUT,
        )
        .await
        .expect("the gateway announces the update to the clients that missed it");
    assert_eq!(announcement["kind"].as_str(), Some("gateway_updated"));
    assert_eq!(
        announcement["agent"].as_str(),
        Some(""),
        "a gateway-owned notification names no agent"
    );
    assert_eq!(
        announcement["title"].as_str(),
        Some(format!("Updated to v{NEWER_VERSION}").as_str())
    );
    assert_eq!(
        announcement["body"].as_str(),
        Some(format!("Your gateway updated to v{NEWER_VERSION}.").as_str())
    );

    destroy_agent(&updated_client, &agent);
}

/// An update killed mid-install: the next boot says so instead of going quiet, clears what the dead
/// backup left behind, and a retry against a reachable release runs to completion.
#[tokio::test]
async fn an_interrupted_update_is_recovered_swept_and_retryable() {
    let stalled = FakeReleaseServer::start(NEWER_VERSION, ArtifactMode::Stall)
        .expect("start the stalling release source");
    let gateway = Gateway::install("interrupted");
    let mut server = gateway.start(stalled.base_url());
    let client = server.client();
    let agent = create_agent(&client, "stalled");
    let leftover = plant_backup_leftover(&gateway, &agent);

    let (status, body) = client.start_gateway_update().expect("POST /gateway/update");
    assert_eq!(status, 202, "the update is accepted: {body}");

    // The download never ends, so the update parks on Applying: exactly where a machine losing
    // power leaves it.
    wait_until("the update to reach the install step", || {
        (gateway.ledger_phase().as_deref() == Some("applying")).then_some(())
    });

    // The kill a power cut is: no shutdown hook, no ledger update, the download simply gone.
    server.shutdown();
    drop(client);
    drop(stalled);

    // The retry needs a release it can actually install.
    let releases = FakeReleaseServer::start(NEWER_VERSION, ArtifactMode::Serve(newer_release_archive()))
        .expect("start the reachable release source");
    let recovered_server = gateway.start(releases.base_url());
    let recovered_client = recovered_server.client();

    let mut sock = recovered_client.open_sync().await.expect("open /sync");
    let (_hello, snapshot) = handshake(&mut sock).await;
    let operation = gateway_of(&snapshot)["operation"].clone();
    assert_eq!(operation["kind"].as_str(), Some("update"));
    assert_eq!(operation["phase"].as_str(), Some("failed"));
    assert_eq!(operation["targetVersion"].as_str(), Some(NEWER_VERSION));
    assert!(
        operation["error"]
            .as_str()
            .is_some_and(|error| error.contains("installing")),
        "the failure says which step died: {operation}"
    );
    assert_eq!(
        gateway.ledger(),
        None,
        "the boot that reported the interruption owns the ledger"
    );

    wait_until("the killed backup's leftover to be swept", || {
        (!container_exists(&leftover)).then_some(())
    });

    let (status, body) = recovered_client
        .start_gateway_update()
        .expect("retry POST /gateway/update");
    assert_eq!(status, 202, "a failed update yields the slot to a retry: {body}");
    let operations = collect_until_phase(&mut sock, "restarting")
        .await
        .expect("the retry reaches the restart");
    assert_phases_in_order(&operations, NEWER_VERSION);

    destroy_agent(&recovered_client, &agent);
}

/// An update that cannot install what it downloaded: the failure keeps projecting with the step it
/// died on, and the dismiss is what ends it. No agent, so the snapshot phase has nothing to do.
#[tokio::test]
async fn a_broken_release_projects_a_failure_until_it_is_dismissed() {
    let releases = FakeReleaseServer::start(NEWER_VERSION, ArtifactMode::Corrupt)
        .expect("start the corrupt release source");
    let gateway = Gateway::install("corrupt");
    let server = gateway.start(releases.base_url());
    let client = server.client();

    let mut sock = client.open_sync().await.expect("open /sync");
    handshake(&mut sock).await;

    let (status, body) = client.start_gateway_update().expect("POST /gateway/update");
    assert_eq!(status, 202, "the update is accepted: {body}");

    let operations = collect_until_phase(&mut sock, "failed")
        .await
        .expect("the update reports its failure");
    let failure = operations.last().expect("a failure frame");
    assert_eq!(failure["targetVersion"].as_str(), Some(NEWER_VERSION));
    let error = failure["error"].as_str().expect("a failure carries its error");
    assert!(error.contains("installing"), "the step it died on: {error}");
    assert!(error.contains("extract"), "what actually went wrong: {error}");
    // The projection leads the ledger clear, so this is the settled state, not the frame's instant.
    wait_until(
        "a failure this vestad reported itself to leave nothing for the next boot",
        || gateway.ledger().is_none().then_some(()),
    );

    let (status, body) = client
        .dismiss_gateway_update()
        .expect("POST /gateway/update/dismiss");
    assert_eq!(status, 200, "the failure is dismissable: {body}");
    assert_eq!(body["dismissed"].as_bool(), Some(true));

    let cleared = sock
        .expect_frame_matching(
            |frame| {
                frame["type"].as_str() == Some("state")
                    && gateway_of(frame)["operation"].is_null()
            },
            PHASE_TIMEOUT,
        )
        .await
        .expect("the dismiss clears the projection");
    assert!(gateway_of(&cleared)["operation"].is_null());
}

/// The maintenance window applies a release the periodic detection poll had not yet cached: it
/// resolves the release freshly at the window rather than trusting the poll's last answer, so a
/// release published between the poll and the window is not missed for a whole day. No manual POST,
/// and no agents, so every window is the current one.
#[tokio::test]
async fn maintenance_applies_a_release_the_cached_check_had_not_yet_seen() {
    let releases =
        FakeReleaseServer::start(NEWER_VERSION, ArtifactMode::Serve(newer_release_archive()))
            .expect("start the fake release source");
    // At boot the source reports only the running version, so the boot-time detection poll caches
    // "no update": exactly the stale answer the window must not trust.
    releases.set_version(env!("CARGO_PKG_VERSION"));

    let gateway = Gateway::install("maintenance")
        .with_auto_update(true)
        .with_settle_secs(MAINTENANCE_SETTLE_SECS);
    let server = gateway.start(releases.base_url());
    let client = server.client();

    let mut sock = client.open_sync().await.expect("open /sync");
    handshake(&mut sock).await;

    // Wait until the boot poll has cached "no update", so the newer release is offered only after
    // the cache the old code trusted already says there is nothing to do.
    wait_until("the boot poll to cache no-update", || {
        let info = client.gateway_version().ok()?;
        (info["update_available"].as_bool() == Some(false)).then_some(())
    });
    releases.set_version(NEWER_VERSION);

    // The maintenance window fires on its own and its fresh check finds the release the cache still
    // calls absent, walking the update to the restart.
    let operations = collect_until_phase(&mut sock, "restarting")
        .await
        .expect("maintenance drives the update to the restart");
    assert_phases_in_order(&operations, NEWER_VERSION);
    wait_until("the service restart to be requested", || {
        gateway.restart_was_requested().then_some(())
    });
    let ledger = gateway.ledger().expect("a restarting update leaves its ledger");
    assert_eq!(ledger["target_version"].as_str(), Some(NEWER_VERSION));
}
