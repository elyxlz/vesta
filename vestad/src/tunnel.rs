use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

const CLOUDFLARED_DOWNLOAD_BASE: &str =
    "https://github.com/cloudflare/cloudflared/releases/latest/download";
const CF_API_BASE: &str = "https://api.cloudflare.com/client/v4";

/// Bound every Cloudflare API curl so a stalled connection can never wedge the
/// caller: the tunnel supervisor runs these calls in its loop and vestad's
/// shutdown awaits that loop.
const CF_API_CONNECT_TIMEOUT_SECS: u64 = 10;
const CF_API_MAX_TIME_SECS: u64 = 60;

#[derive(Serialize, Deserialize, Clone)]
pub struct TunnelConfig {
    pub tunnel_id: String,
    pub tunnel_token: String,
    pub hostname: String,
    pub dns_record_id: Option<String>,
}

impl TunnelConfig {
    /// The public https URL this tunnel serves.
    pub fn url(&self) -> String {
        format!("https://{}", self.hostname)
    }
}

/// Self-hosted (BYOK) Cloudflare credentials, persisted to `cloudflare.json`.
///
/// The public vestad binary ships **no** Cloudflare token — a self-hoster brings
/// their own, scoped to a domain they control (Account → Cloudflare Tunnel: Edit,
/// Zone → DNS: Edit, Zone → Zone: Read). Managed (vesta.run) VMs never reach this
/// path: the control plane creates the tunnel and seeds `tunnel.json` directly.
#[derive(Serialize, Deserialize, Clone, PartialEq, Eq)]
pub(crate) struct CloudflareCreds {
    pub(crate) api_token: String,
    pub(crate) account_id: String,
    pub(crate) zone_id: String,
}

fn cf_creds_path(config_dir: &Path) -> PathBuf {
    config_dir.join("cloudflare.json")
}

/// True iff usable Cloudflare credentials already exist (saved file or env).
pub fn has_cf_creds(config_dir: &Path) -> bool {
    cf_creds_path(config_dir).exists()
        || (std::env::var("CLOUDFLARE_API_TOKEN").is_ok()
            && std::env::var("CLOUDFLARE_ACCOUNT_ID").is_ok()
            && std::env::var("CLOUDFLARE_ZONE_ID").is_ok())
}

fn no_tunnel_marker_path(config_dir: &Path) -> PathBuf {
    config_dir.join("no_tunnel")
}

/// True once the user has explicitly skipped domain setup (empty input at the
/// first-run prompt), so `run_server_systemd` doesn't re-prompt on every
/// subsequent `vestad start`.
pub fn has_declined_tunnel(config_dir: &Path) -> bool {
    no_tunnel_marker_path(config_dir).exists()
}

/// Persist "the user does not want a tunnel" (written by `vestad tunnel
/// destroy` and the skipped first-run prompt) so neither boot nor the
/// supervisor recreates one until `vestad connect` clears it.
pub fn decline_tunnel(config_dir: &Path) -> Result<(), String> {
    write_secret_file(&no_tunnel_marker_path(config_dir), "", "no-tunnel preference")
}

/// Clear the declined-tunnel preference: a successful `vestad connect` means
/// the user wants a tunnel again.
pub(crate) fn clear_declined_tunnel(config_dir: &Path) {
    std::fs::remove_file(no_tunnel_marker_path(config_dir)).ok();
}

/// Write `contents` to `path` 0600, creating the parent dir. Single owner of the
/// "persist a secret config file" pattern; `what` names the file in write errors.
fn write_secret_file(path: &Path, contents: &str, what: &str) -> Result<(), String> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| format!("failed to create config dir: {e}"))?;
    }
    std::fs::write(path, contents).map_err(|e| format!("failed to write {what}: {e}"))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600)).ok();
    }
    Ok(())
}

pub(crate) fn save_cf_creds(config_dir: &Path, creds: &CloudflareCreds) -> Result<(), String> {
    write_secret_file(
        &cf_creds_path(config_dir),
        &serde_json::to_string_pretty(creds).expect("cloudflare creds serialize to json"),
        "cloudflare creds",
    )
}

/// Resolve Cloudflare credentials for self-hosted tunnel management.
///
/// Order: the saved `cloudflare.json` (written by `vestad connect` /
/// first-run setup), then env vars (power users + CI). There is NO baked
/// build-time token anymore — the public binary carries no shared credential.
fn cf_env(config_dir: &Path) -> Result<CloudflareCreds, String> {
    if let Ok(data) = std::fs::read_to_string(cf_creds_path(config_dir)) {
        if let Ok(creds) = serde_json::from_str::<CloudflareCreds>(&data) {
            return Ok(creds);
        }
    }
    let api_token = std::env::var("CLOUDFLARE_API_TOKEN").map_err(|_| {
        "no Cloudflare credentials — run `vestad connect` to connect your domain".to_string()
    })?;
    let account_id = std::env::var("CLOUDFLARE_ACCOUNT_ID")
        .map_err(|_| "CLOUDFLARE_ACCOUNT_ID not set".to_string())?;
    let zone_id = std::env::var("CLOUDFLARE_ZONE_ID")
        .map_err(|_| "CLOUDFLARE_ZONE_ID not set".to_string())?;
    Ok(CloudflareCreds {
        api_token,
        account_id,
        zone_id,
    })
}

fn prompt(label: &str) -> Result<String, String> {
    use std::io::Write;
    eprint!("{label}");
    std::io::stderr().flush().ok();
    let mut s = String::new();
    std::io::stdin()
        .read_line(&mut s)
        .map_err(|e| format!("failed to read input: {e}"))?;
    Ok(s.trim().to_string())
}

/// Interactively collect + validate BYOK Cloudflare credentials, then persist
/// them (0600). The user pastes just their domain + an API token; the zone id and
/// account id are auto-discovered from the domain, so there are no opaque IDs to
/// copy. Returns the resolved creds on success.
pub fn setup_cf_creds_interactive(config_dir: &Path) -> Result<(), String> {
    use std::io::IsTerminal;

    if !std::io::stdin().is_terminal() {
        return Err(
            "connecting a domain needs an interactive terminal. Run `vestad connect` \
             from a shell, or set CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID / \
             CLOUDFLARE_ZONE_ID in the environment. (Or run `vestad --standalone --no-tunnel` \
             to run locally without a tunnel.)"
                .to_string(),
        );
    }

    eprintln!();
    eprintln!("  \x1b[1;35mConnect your domain\x1b[0m");
    eprintln!();
    eprintln!("  Vesta creates a secure Cloudflare tunnel to this machine and a DNS");
    eprintln!("  record for it, on a domain you own in Cloudflare. That needs an API token.");
    eprintln!();
    eprintln!("  Create one at https://dash.cloudflare.com/profile/api-tokens");
    eprintln!("  → Create Token → Create Custom Token, with these permissions:");
    eprintln!("    • Account → Cloudflare Tunnel → Edit");
    eprintln!("    • Zone     → DNS            → Edit");
    eprintln!("    • Zone     → Zone           → Read");
    eprintln!("  Scope it to your account and your domain, then paste it below.");
    eprintln!(
        "  It's stored only on this machine ({}), never sent anywhere else.",
        cf_creds_path(config_dir).display()
    );
    eprintln!();

    let domain =
        prompt("  your domain (press enter to skip, local network only): ")?.to_lowercase();
    if domain.is_empty() {
        decline_tunnel(config_dir)?;
        eprintln!();
        eprintln!(
            "  no public URL yet. your agent works on this machine and your LAN. \
             run `vestad connect` anytime to add one."
        );
        eprintln!();
        return Ok(());
    }
    let api_token = prompt("  Cloudflare API token: ")?;
    if api_token.is_empty() {
        return Err("no token entered".into());
    }

    eprintln!("  verifying token and looking up zone…");
    let zones_url = format!("{CF_API_BASE}/zones?name={domain}");
    let resp = cf_request("GET", &zones_url, &api_token, None)
        .map_err(|e| format!("could not verify token / find zone: {e}"))?;
    let zone = resp["result"]
        .as_array()
        .and_then(|a| a.first())
        .ok_or_else(|| {
            format!(
                "no Cloudflare zone found for '{domain}'. Add the domain to your Cloudflare \
                 account first, and make sure the token can read it."
            )
        })?;
    let zone_id = zone["id"]
        .as_str()
        .ok_or("zone lookup response missing zone id")?
        .to_string();
    let account_id = zone["account"]["id"]
        .as_str()
        .ok_or("zone lookup response missing account id")?
        .to_string();

    save_cf_creds(
        config_dir,
        &CloudflareCreds {
            api_token,
            account_id,
            zone_id,
        },
    )?;
    clear_declined_tunnel(config_dir);
    eprintln!("  \x1b[32m✓\x1b[0m connected to {domain}");
    eprintln!();
    Ok(())
}

fn cf_request(
    method: &str,
    url: &str,
    api_token: &str,
    body: Option<serde_json::Value>,
) -> Result<serde_json::Value, String> {
    use std::io::Write;
    use std::process::Stdio;

    // The token goes to curl on stdin (`-H @-`), never in argv, where any local user sees it.
    let mut cmd = std::process::Command::new("curl");
    cmd.args(["-sS", "-X", method, url])
        .arg("--connect-timeout")
        .arg(CF_API_CONNECT_TIMEOUT_SECS.to_string())
        .arg("--max-time")
        .arg(CF_API_MAX_TIME_SECS.to_string())
        .args(["-H", "@-"])
        .arg("-H")
        .arg("Content-Type: application/json");

    if let Some(b) = body {
        cmd.arg("-d").arg(b.to_string());
    }

    let mut child = cmd
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("curl failed: {e}"))?;
    let header_written = child
        .stdin
        .take()
        .ok_or_else(|| "curl stdin is not piped".to_string())
        .and_then(|mut stdin| {
            stdin
                .write_all(format!("Authorization: Bearer {api_token}\n").as_bytes())
                .map_err(|e| format!("could not pass the token to curl: {e}"))
        });
    let output = child
        .wait_with_output()
        .map_err(|e| format!("curl failed: {e}"))?;
    header_written?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("cloudflare API request failed: {stderr}"));
    }

    let resp: serde_json::Value = serde_json::from_slice(&output.stdout)
        .map_err(|e| format!("failed to parse cloudflare response: {e}"))?;

    if resp["success"].as_bool() != Some(true) {
        let errors = &resp["errors"];
        return Err(format!("cloudflare API error: {errors}"));
    }

    Ok(resp)
}

fn get_zone_domain(env: &CloudflareCreds) -> Result<String, String> {
    let url = format!("{}/zones/{}", CF_API_BASE, env.zone_id);
    let resp = cf_request("GET", &url, &env.api_token, None)?;
    resp["result"]["name"]
        .as_str()
        .map(std::string::ToString::to_string)
        .ok_or_else(|| "failed to get domain name from zone".to_string())
}

fn delete_tunnel_if_exists(env: &CloudflareCreds, tunnel_name: &str) {
    let list_url = format!(
        "{}/accounts/{}/cfd_tunnel?name={}",
        CF_API_BASE, env.account_id, tunnel_name
    );
    let Ok(resp) = cf_request("GET", &list_url, &env.api_token, None) else {
        return;
    };
    if let Some(tunnels) = resp["result"].as_array() {
        for tunnel in tunnels {
            if tunnel["deleted_at"].is_null() {
                if let Some(id) = tunnel["id"].as_str() {
                    let del_url = format!(
                        "{}/accounts/{}/cfd_tunnel/{}",
                        CF_API_BASE, env.account_id, id
                    );
                    tracing::info!(tunnel_id = %id, "deleting stale tunnel");
                    cf_request("DELETE", &del_url, &env.api_token, None).ok();
                }
            }
        }
    }
}

fn delete_dns_record_if_exists(env: &CloudflareCreds, subdomain: &str) {
    let Ok(domain) = get_zone_domain(env) else {
        return;
    };
    let fqdn = format!("{subdomain}.{domain}");
    let list_url = format!(
        "{}/zones/{}/dns_records?type=CNAME&name={}",
        CF_API_BASE, env.zone_id, fqdn
    );
    let Ok(resp) = cf_request("GET", &list_url, &env.api_token, None) else {
        return;
    };
    if let Some(records) = resp["result"].as_array() {
        for record in records {
            if let Some(id) = record["id"].as_str() {
                let del_url = format!("{}/zones/{}/dns_records/{}", CF_API_BASE, env.zone_id, id);
                tracing::info!(record_id = %id, "deleting stale DNS record");
                cf_request("DELETE", &del_url, &env.api_token, None).ok();
            }
        }
    }
}

fn tunnel_config_path(config_dir: &Path) -> PathBuf {
    config_dir.join("tunnel.json")
}

pub fn get_tunnel_config(config_dir: &Path) -> Option<TunnelConfig> {
    let path = tunnel_config_path(config_dir);
    let data = std::fs::read_to_string(&path).ok()?;
    serde_json::from_str(&data).ok()
}

const ANIMALS: &[&str] = &[
    "alpaca",
    "badger",
    "beaver",
    "bison",
    "bobcat",
    "camel",
    "capybara",
    "cardinal",
    "caribou",
    "chameleon",
    "cheetah",
    "chinchilla",
    "chipmunk",
    "cobra",
    "condor",
    "cougar",
    "coyote",
    "crane",
    "cricket",
    "crow",
    "dingo",
    "dolphin",
    "donkey",
    "eagle",
    "egret",
    "elk",
    "falcon",
    "ferret",
    "finch",
    "flamingo",
    "fox",
    "gazelle",
    "gecko",
    "gopher",
    "grizzly",
    "grouse",
    "gull",
    "hamster",
    "hawk",
    "hedgehog",
    "heron",
    "hornet",
    "hyena",
    "ibex",
    "iguana",
    "impala",
    "jackal",
    "jaguar",
    "jay",
    "kestrel",
    "kingfisher",
    "kiwi",
    "koala",
    "komodo",
    "lark",
    "lemur",
    "leopard",
    "lion",
    "llama",
    "lobster",
    "lynx",
    "macaw",
    "mamba",
    "manatee",
    "mantis",
    "marmot",
    "marten",
    "merlin",
    "mink",
    "mongoose",
    "moose",
    "narwhal",
    "newt",
    "ocelot",
    "okapi",
    "opossum",
    "osprey",
    "otter",
    "owl",
    "panda",
    "panther",
    "parrot",
    "pelican",
    "penguin",
    "phoenix",
    "pika",
    "piranha",
    "python",
    "quail",
    "raven",
    "robin",
    "salmon",
    "scorpion",
    "shark",
    "shrike",
    "sparrow",
    "squid",
    "stork",
    "swift",
    "tapir",
    "tern",
    "tiger",
    "toucan",
    "turtle",
    "viper",
    "vulture",
    "walrus",
    "whale",
    "wolf",
    "wolverine",
    "wombat",
    "wren",
    "yak",
    "zebra",
    "aardvark",
    "aardwolf",
    "abalone",
    "addax",
    "adder",
    "agouti",
    "albacore",
    "albatross",
    "anaconda",
    "anchovy",
    "angelfish",
    "anole",
    "ant",
    "anteater",
    "antelope",
    "antlion",
    "aphid",
    "armadillo",
    "auk",
    "avocet",
    "axolotl",
    "baboon",
    "bandicoot",
    "barb",
    "barbet",
    "barnacle",
    "barracuda",
    "basilisk",
    "bass",
    "bat",
    "batfish",
    "bear",
    "bee",
    "beetle",
    "beluga",
    "betta",
    "bilby",
    "bittern",
    "blenny",
    "bluebird",
    "bluegill",
    "boa",
    "bobolink",
    "bonefish",
    "bongo",
    "bonito",
    "bonobo",
    "brant",
    "bream",
    "bullfrog",
    "bullhead",
    "bumblebee",
    "bunting",
    "butterfly",
    "caiman",
    "canary",
    "capuchin",
    "caracal",
    "carp",
    "cassowary",
    "cat",
    "catbird",
    "catfish",
    "catshark",
    "centipede",
    "chafer",
    "chaffinch",
    "chamois",
    "char",
    "chickadee",
    "chimp",
    "chub",
    "cicada",
    "cichlid",
    "civet",
    "clam",
    "clownfish",
    "coati",
    "cockle",
    "cod",
    "colobus",
    "copperhead",
    "cormorant",
    "cowbird",
    "cowfish",
    "cowrie",
    "crab",
    "crake",
    "crappie",
    "crayfish",
    "crocodile",
    "crossbill",
    "cuckoo",
    "curlew",
    "cusk",
    "dab",
    "dace",
    "damselfly",
    "puffin",
    "dikdik",
    "dipper",
    "dog",
    "dogfish",
    "dorado",
    "dormouse",
    "dove",
    "dragonfly",
    "duck",
    "dugong",
    "dunlin",
    "dunnock",
    "earwig",
    "echidna",
    "eel",
    "eider",
    "eland",
    "elephant",
    "emu",
    "ermine",
    "fennec",
    "firefly",
    "fisher",
    "flea",
    "flicker",
    "flounder",
    "fossa",
    "frog",
    "fulmar",
    "gannet",
    "garfish",
    "gator",
    "gemsbok",
    "genet",
    "gerbil",
    "gibbon",
    "giraffe",
    "gnat",
    "gharial",
    "goat",
    "goatfish",
    "goby",
    "godwit",
    "goldfinch",
    "goldfish",
    "goose",
    "gorilla",
    "grackle",
    "grebe",
    "greenfinch",
    "grosbeak",
    "grouper",
    "grub",
    "grunion",
    "grunt",
    "guan",
    "guanaco",
    "guppy",
    "haddock",
    "hake",
    "halibut",
    "kinglet",
    "harrier",
    "hawfinch",
    "herring",
    "hippo",
    "hoopoe",
    "hornbill",
    "horse",
    "hoverfly",
    "hyrax",
    "ibis",
    "jackdaw",
    "jackrabbit",
    "jaeger",
    "jerboa",
    "junco",
    "kakapo",
    "kangaroo",
    "katydid",
    "kea",
    "killdeer",
    "kingfish",
    "kinkajou",
    "kite",
    "koi",
    "kookaburra",
    "krill",
    "kudu",
    "ladybug",
    "langur",
    "lapwing",
    "lemming",
    "limpet",
    "limpkin",
    "ling",
    "linnet",
    "lizard",
    "loach",
    "locust",
    "lorikeet",
    "lungfish",
    "macaque",
    "mackerel",
    "magpie",
    "mahi",
    "mallard",
    "mandrill",
    "manta",
    "margay",
    "marmoset",
    "mayfly",
    "meerkat",
    "merganser",
    "midge",
    "millipede",
    "minnow",
    "mole",
    "loris",
    "monkey",
    "moorhen",
    "mosquito",
    "moth",
    "motmot",
    "mouse",
    "mudskipper",
    "mule",
    "mullet",
    "muskox",
    "muskrat",
    "mussel",
    "myna",
    "nautilus",
    "nightjar",
    "numbat",
    "nutcracker",
    "nuthatch",
    "nutria",
    "opah",
    "orangutan",
    "oribi",
    "oriole",
    "oryx",
    "oscar",
    "ostrich",
    "oyster",
    "paca",
    "pangolin",
    "partridge",
    "peacock",
    "peafowl",
    "peccary",
    "peeper",
    "perch",
    "petrel",
    "pheasant",
    "pigeon",
    "pike",
    "pillbug",
    "pinfish",
    "pintail",
    "pipit",
    "platypus",
    "plover",
    "polecat",
    "pollock",
    "pompano",
    "pony",
    "porcupine",
    "porpoise",
    "potoroo",
    "prawn",
    "pronghorn",
    "pupfish",
    "quetzal",
    "quokka",
    "quoll",
    "rabbit",
    "raccoon",
    "ram",
    "rattler",
    "ray",
    "redfish",
    "redpoll",
    "redstart",
    "redwing",
    "remora",
    "rhino",
    "ptarmigan",
    "rook",
    "sable",
    "sailfish",
    "salamander",
    "sandpiper",
    "sardine",
    "sawfly",
    "scallop",
    "scoter",
    "seal",
    "serval",
    "shad",
    "sheep",
    "shiner",
    "shoebill",
    "shrew",
    "shrimp",
    "silverfish",
    "siskin",
    "skate",
    "skink",
    "skylark",
    "sloth",
    "slug",
    "smelt",
    "smew",
    "snail",
    "snapper",
    "snipe",
    "snook",
    "marlin",
    "spider",
    "spoonbill",
    "sprat",
    "springbok",
    "squirrel",
    "stallion",
    "starfish",
    "starling",
    "stilt",
    "stingray",
    "stoat",
    "sturgeon",
    "sunbird",
    "sunfish",
    "swallow",
    "swan",
    "swordfish",
    "tamarin",
    "tanager",
    "tang",
    "tarantula",
    "tarpon",
    "tayra",
    "teal",
    "tenrec",
    "termite",
    "terrapin",
    "tetra",
    "thrasher",
    "thrush",
    "tick",
    "tilapia",
    "tilefish",
    "toadfish",
    "tody",
    "tortoise",
    "towhee",
    "trogon",
    "trout",
    "tuna",
    "urchin",
    "verdin",
    "vervet",
    "vicuna",
    "vireo",
    "vole",
    "wagtail",
    "wahoo",
    "wallaby",
    "wallaroo",
    "walleye",
    "warbler",
    "warthog",
    "wasp",
    "waxwing",
    "weaver",
    "weevil",
    "wheatear",
    "whelk",
    "whiptail",
    "wigeon",
    "wildcat",
    "willet",
    "wolffish",
    "wrasse",
    "wryneck",
    "zebu",
];

fn animal_for_user(username: &str, offset: usize) -> &'static str {
    let mut hash: u64 = 5381;
    for byte in username.bytes() {
        hash = hash.wrapping_mul(33).wrapping_add(u64::from(byte));
    }
    let base = usize::try_from(hash % ANIMALS.len() as u64).expect("modulo keeps index below ANIMALS.len()");
    ANIMALS[(base + offset) % ANIMALS.len()]
}

/// Sanitize a string to only contain lowercase alphanumeric characters and hyphens.
fn sanitize(s: &str) -> String {
    let cleaned: String = s
        .to_lowercase()
        .replace(|c: char| !c.is_alphanumeric(), "-");
    cleaned.trim_matches('-').to_string()
}

/// Upper bound on names tried before giving up: every animal three times over (bare, `-2`, `-3`).
const SUBDOMAIN_PICK_MAX_ATTEMPTS: usize = 3 * ANIMALS.len();
const DNS_LABEL_MAX_LEN: usize = 63;

/// The gateway's generated subdomain at `offset`: the Linux user's animal first, then the next
/// animals, then the same names numbered (`otter-2`) once the list is spent.
fn generate_subdomain(offset: usize) -> String {
    let animal = animal_for_user(&crate::paths::current_user(), offset % ANIMALS.len());
    match offset / ANIMALS.len() {
        0 => animal.to_string(),
        round => format!("{animal}-{}", round + 1),
    }
}

/// An explicit `VESTA_SUBDOMAIN` pin, when set.
fn subdomain_pin() -> Option<String> {
    std::env::var("VESTA_SUBDOMAIN")
        .ok()
        .map(|s| sanitize(&s))
        .filter(|s| !s.is_empty())
}

pub(crate) fn is_valid_subdomain(subdomain: &str) -> bool {
    !subdomain.is_empty()
        && subdomain.len() <= DNS_LABEL_MAX_LEN
        && !subdomain.starts_with('-')
        && !subdomain.ends_with('-')
        && subdomain
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}

/// The first generated name nobody holds. A failed check stops the pick: assuming a name is free
/// would let `setup_tunnel` delete another gateway's tunnel.
fn pick_free_subdomain(
    mut is_taken: impl FnMut(&str) -> Result<bool, String>,
) -> Result<String, String> {
    for offset in 0..SUBDOMAIN_PICK_MAX_ATTEMPTS {
        let candidate = generate_subdomain(offset);
        if !is_taken(&candidate)? {
            return Ok(candidate);
        }
    }
    Err("no free subdomain left in this zone".to_string())
}

/// Whether `subdomain` already has a DNS record in the zone or a live tunnel of our naming.
fn subdomain_taken(env: &CloudflareCreds, domain: &str, subdomain: &str) -> Result<bool, String> {
    let dns_url = format!(
        "{CF_API_BASE}/zones/{}/dns_records?name={subdomain}.{domain}",
        env.zone_id
    );
    let dns = cf_request("GET", &dns_url, &env.api_token, None)?;
    if dns["result"]
        .as_array()
        .is_some_and(|records| !records.is_empty())
    {
        return Ok(true);
    }
    let tunnel_url = format!(
        "{CF_API_BASE}/accounts/{}/cfd_tunnel?name=vesta-{subdomain}&is_deleted=false",
        env.account_id
    );
    let tunnels = cf_request("GET", &tunnel_url, &env.api_token, None)?;
    Ok(tunnels["result"]
        .as_array()
        .is_some_and(|list| !list.is_empty()))
}

/// Create this gateway's tunnel under `explicit` (which must be free) or the first free animal.
fn create_unpinned_tunnel(
    config_dir: &Path,
    env: &CloudflareCreds,
    explicit: Option<&str>,
) -> Result<TunnelConfig, String> {
    let domain = get_zone_domain(env)?;
    let subdomain = choose_subdomain(explicit, &domain, |name| {
        subdomain_taken(env, &domain, name)
    })?;
    setup_tunnel(config_dir, &subdomain)
}

/// `explicit` when nobody holds it (a taken explicit name is an error, never a fallback), else
/// the first free generated name.
fn choose_subdomain(
    explicit: Option<&str>,
    domain: &str,
    mut is_taken: impl FnMut(&str) -> Result<bool, String>,
) -> Result<String, String> {
    match explicit {
        Some(name) if is_taken(name)? => {
            Err(format!("subdomain '{name}' is already in use in {domain}"))
        }
        Some(name) => Ok(name.to_string()),
        None => pick_free_subdomain(is_taken),
    }
}

pub(crate) fn gethostname() -> String {
    let output = std::process::Command::new("hostname")
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
        .unwrap_or_default();
    if output.is_empty() {
        "vesta".to_string()
    } else {
        output
    }
}

/// Full self-host connect flow (`vestad connect`): collect the user's own
/// Cloudflare credentials, make sure cloudflared is present, then create (or
/// reuse) the tunnel. Returns the live tunnel config so the caller can show the
/// URL. This is the one command a self-hoster needs — they never have to discover
/// `tunnel setup`.
pub fn connect_interactive(config_dir: &Path) -> Result<TunnelConfig, String> {
    setup_cf_creds_interactive(config_dir)?;
    ensure_cloudflared(config_dir)?;
    ensure_tunnel(config_dir)
}

pub fn ensure_tunnel(config_dir: &Path) -> Result<TunnelConfig, String> {
    // Managed (vesta.run) VMs: the control plane creates the tunnel + DNS and
    // SEEDS tunnel.json into the config dir. vestad holds no Cloudflare account
    // credential here, so it must NEVER call the Cloudflare API — it just uses the
    // seeded config as-is. This is the load-bearing half of removing the baked
    // fleet-wide token: a managed box can run its one tunnel but cannot touch the
    // zone or any other tunnel.
    if crate::is_cloud_managed() {
        return get_tunnel_config(config_dir)
            .ok_or_else(|| "managed mode: no tunnel.json seeded by the control plane".to_string());
    }

    ensure_tunnel_with(config_dir, subdomain_pin().as_deref())
}

/// The boot converge. A saved tunnel is authoritative: only an explicit pin that differs from it
/// recreates it. Without a saved tunnel, a pin is used as given and anything else takes a free name.
fn ensure_tunnel_with(config_dir: &Path, pin: Option<&str>) -> Result<TunnelConfig, String> {
    if let Some(saved) = get_tunnel_config(config_dir) {
        let current = saved.hostname.split('.').next().unwrap_or("").to_string();
        match pin {
            None => return Ok(saved),
            Some(pinned) if pinned == current => return Ok(saved),
            Some(pinned) => {
                tracing::info!(old = %current, new = %pinned, "pinned subdomain changed, recreating");
                destroy_tunnel(config_dir).map_err(|e| {
                    format!("could not destroy the old tunnel to recreate it (keeping the saved config): {e}")
                })?;
            }
        }
    }
    match pin {
        Some(pinned) => setup_tunnel(config_dir, pinned),
        None => create_unpinned_tunnel(config_dir, &cf_env(config_dir)?, None),
    }
}

/// Provision's tunnel step: keep a tunnel this gateway already has (and the credentials that made
/// it), or store the operator's credentials and create one under `explicit` or the first free animal.
pub(crate) fn provision_tunnel(
    config_dir: &Path,
    creds: &CloudflareCreds,
    explicit: Option<&str>,
) -> Result<TunnelConfig, String> {
    clear_declined_tunnel(config_dir);
    if let Some(saved) = get_tunnel_config(config_dir) {
        if explicit.is_some_and(|name| !saved.hostname.starts_with(&format!("{name}."))) {
            eprintln!(
                "warning: this gateway already has the tunnel {}; ignoring `subdomain`",
                saved.hostname
            );
        }
        if cf_env(config_dir).ok().as_ref() != Some(creds) {
            eprintln!(
                "warning: this gateway keeps the Cloudflare credentials of its tunnel {}; ignoring `cloudflare`",
                saved.hostname
            );
        }
        return Ok(saved);
    }
    ensure_cloudflared(config_dir)?;
    save_cf_creds(config_dir, creds)?;
    create_unpinned_tunnel(config_dir, creds, explicit)
}

/// Supervisor establish: converge tunnel.json without ever rewriting an
/// existing config. An existing config is authoritative here, whatever its
/// subdomain (reconciling a changed subdomain belongs to `vestad connect`
/// and the boot converge); a tunnel the user declined or destroyed stays
/// down; everything else (managed seed wait, BYOK creation) delegates to
/// `ensure_tunnel`.
fn establish_tunnel(config_dir: &Path) -> Result<TunnelConfig, String> {
    if let Some(saved) = get_tunnel_config(config_dir) {
        return Ok(saved);
    }
    if has_declined_tunnel(config_dir) {
        return Err("tunnel declined by the user: run `vestad connect` to enable one".to_string());
    }
    ensure_tunnel(config_dir)
}

pub fn setup_tunnel(config_dir: &Path, subdomain: &str) -> Result<TunnelConfig, String> {
    let env = cf_env(config_dir)?;
    let domain = get_zone_domain(&env)?;
    let tunnel_name = format!("vesta-{subdomain}");

    tracing::info!(tunnel = %tunnel_name, "creating tunnel");
    delete_tunnel_if_exists(&env, &tunnel_name);
    delete_dns_record_if_exists(&env, subdomain);

    let config = create_tunnel_records(
        &mut |method, url, body| cf_request(method, url, &env.api_token, body),
        &env,
        subdomain,
        &domain,
        |config| {
            write_secret_file(
                &tunnel_config_path(config_dir),
                &serde_json::to_string_pretty(config).expect("tunnel config serializes to json"),
                "tunnel config",
            )
        },
    )?;
    tracing::info!(hostname = %config.hostname, "tunnel ready");
    Ok(config)
}

/// One Cloudflare API call: method, url, optional JSON body.
type CfCall<'a> =
    dyn FnMut(&str, &str, Option<serde_json::Value>) -> Result<serde_json::Value, String> + 'a;

/// Create the tunnel, fetch its token, point a DNS record at it, then `persist` the config. A
/// failed step deletes what the earlier steps created, so a failed run leaves no tunnel or record
/// behind to block a re-run under the same subdomain.
fn create_tunnel_records(
    cf: &mut CfCall<'_>,
    env: &CloudflareCreds,
    subdomain: &str,
    domain: &str,
    persist: impl FnOnce(&TunnelConfig) -> Result<(), String>,
) -> Result<TunnelConfig, String> {
    let tunnel_secret = hex::encode(rand::random::<[u8; 32]>());
    let secret_b64 = {
        use base64::Engine;
        base64::engine::general_purpose::STANDARD.encode(tunnel_secret.as_bytes())
    };
    let resp = cf(
        "POST",
        &format!("{CF_API_BASE}/accounts/{}/cfd_tunnel", env.account_id),
        Some(serde_json::json!({
            "name": format!("vesta-{subdomain}"),
            "tunnel_secret": secret_b64,
            "config_src": "local",
        })),
    )?;
    let tunnel_id = resp["result"]["id"]
        .as_str()
        .ok_or("missing tunnel id in response")?
        .to_string();

    let routed = route_tunnel(cf, env, subdomain, domain, &tunnel_id, persist);
    if routed.is_err() {
        let tunnel_url = format!(
            "{CF_API_BASE}/accounts/{}/cfd_tunnel/{tunnel_id}",
            env.account_id
        );
        roll_back(cf, &tunnel_url, "tunnel");
    }
    routed
}

/// The steps after the tunnel exists; on a failed `persist` it deletes the DNS record it created.
fn route_tunnel(
    cf: &mut CfCall<'_>,
    env: &CloudflareCreds,
    subdomain: &str,
    domain: &str,
    tunnel_id: &str,
    persist: impl FnOnce(&TunnelConfig) -> Result<(), String>,
) -> Result<TunnelConfig, String> {
    let token_url = format!(
        "{CF_API_BASE}/accounts/{}/cfd_tunnel/{tunnel_id}/token",
        env.account_id
    );
    let tunnel_token = cf("GET", &token_url, None)?["result"]
        .as_str()
        .ok_or("missing tunnel token in response")?
        .to_string();

    let hostname = format!("{subdomain}.{domain}");
    tracing::info!(hostname = %hostname, tunnel_id = %tunnel_id, "creating DNS record");
    let dns_resp = cf(
        "POST",
        &format!("{CF_API_BASE}/zones/{}/dns_records", env.zone_id),
        Some(serde_json::json!({
            "type": "CNAME",
            "name": subdomain,
            "content": format!("{tunnel_id}.cfargotunnel.com"),
            "proxied": true,
        })),
    )?;
    let config = TunnelConfig {
        tunnel_id: tunnel_id.to_string(),
        tunnel_token,
        hostname,
        dns_record_id: dns_resp["result"]["id"].as_str().map(ToString::to_string),
    };

    if let Err(error) = persist(&config) {
        if let Some(record_id) = &config.dns_record_id {
            let record_url = format!(
                "{CF_API_BASE}/zones/{}/dns_records/{record_id}",
                env.zone_id
            );
            roll_back(cf, &record_url, "DNS record");
        }
        return Err(error);
    }
    Ok(config)
}

/// Best-effort delete of something this run created; a failed delete is logged, never raised,
/// so the caller still reports the error that caused the rollback.
fn roll_back(cf: &mut CfCall<'_>, url: &str, what: &str) {
    if let Err(error) = cf("DELETE", url, None) {
        tracing::warn!(url = %url, "could not delete the {what} this run created: {error}");
    }
}

pub fn destroy_tunnel(config_dir: &Path) -> Result<(), String> {
    let config = get_tunnel_config(config_dir).ok_or("no tunnel configured")?;

    let env = cf_env(config_dir)?;

    if let Some(record_id) = &config.dns_record_id {
        tracing::info!("deleting DNS record");
        let dns_url = format!(
            "{}/zones/{}/dns_records/{}",
            CF_API_BASE, env.zone_id, record_id
        );
        cf_request("DELETE", &dns_url, &env.api_token, None).ok();
    }

    tracing::info!(tunnel_id = %config.tunnel_id, "deleting tunnel");
    let tunnel_url = format!(
        "{}/accounts/{}/cfd_tunnel/{}",
        CF_API_BASE, env.account_id, config.tunnel_id
    );
    cf_request("DELETE", &tunnel_url, &env.api_token, None)
        .map_err(|e| format!("failed to delete tunnel: {e}"))?;

    std::fs::remove_file(tunnel_config_path(config_dir)).ok();
    tracing::info!("tunnel destroyed");
    Ok(())
}

pub fn ensure_cloudflared(config_dir: &Path) -> Result<PathBuf, String> {
    if let Some(path) = crate::vendored_bin::which("cloudflared") {
        return Ok(path);
    }

    if let Some((bytes, fingerprint)) = crate::vendored_bin::vendored_cloudflared() {
        return crate::vendored_bin::extract_embedded(config_dir, "cloudflared", bytes, fingerprint)
            .map_err(|e| e.to_string());
    }

    let local_bin = config_dir.join("cloudflared");
    if local_bin.exists() {
        return Ok(local_bin);
    }

    let arch = match std::env::consts::ARCH {
        "x86_64" => "amd64",
        "aarch64" => "arm64",
        other => {
            return Err(format!(
                "unsupported architecture for cloudflared: {other}"
            ))
        }
    };

    let url = format!("{CLOUDFLARED_DOWNLOAD_BASE}/cloudflared-linux-{arch}");
    tracing::info!(url = %url, "downloading cloudflared");

    std::fs::create_dir_all(config_dir)
        .map_err(|e| format!("failed to create config dir: {e}"))?;

    let status = std::process::Command::new("curl")
        .args(["-fsSL", "-o"])
        .arg(&local_bin)
        .arg(&url)
        .status()
        .map_err(|e| format!("curl failed: {e}"))?;

    if !status.success() {
        return Err("failed to download cloudflared".to_string());
    }

    crate::vendored_bin::set_executable(&local_bin).map_err(|e| e.to_string())?;

    tracing::info!(path = %local_bin.display(), "cloudflared downloaded");
    Ok(local_bin)
}

/// Spawn one cloudflared run for the configured tunnel. Returns the child and
/// the loopback port of its metrics server (for /ready probing).
fn start_tunnel(
    config_dir: &Path,
    port: u16,
) -> Result<(tokio::process::Child, u16), String> {
    let tc = get_tunnel_config(config_dir)
        .ok_or("no tunnel configured — run `vestad tunnel setup <subdomain>` first")?;

    let cloudflared = ensure_cloudflared(config_dir)?;

    let cf_config_path = config_dir.join("cloudflared.yml");
    let cf_config = format!(
        "tunnel: {tunnel_id}\n\
         ingress:\n\
         \x20 - hostname: {hostname}\n\
         \x20   service: https://localhost:{port}\n\
         \x20   originRequest:\n\
         \x20     noTLSVerify: true\n\
         \x20 - service: http_status:404\n",
        tunnel_id = tc.tunnel_id,
        hostname = tc.hostname,
        port = port,
    );
    std::fs::write(&cf_config_path, &cf_config)
        .map_err(|e| format!("failed to write cloudflared config: {e}"))?;

    // Loopback metrics server: exposes cloudflared's /ready endpoint, which the
    // supervisor probes for registered edge connections. Bind-and-drop to pick a
    // free port; if something grabs it before cloudflared does, cloudflared exits
    // and the supervisor respawns with a fresh port.
    let metrics_port = alloc_loopback_port()?;
    let metrics_addr = format!("127.0.0.1:{metrics_port}");

    // Force HTTP/2 over TCP instead of the QUIC/UDP default. Home and laptop NAT
    // devices aggressively time out idle UDP flows, which silently drops the
    // tunnel and yields error 1033 on the next request (e.g. the first file
    // share after an idle period). TCP keeps the connection alive far longer.
    let mut child = tokio::process::Command::new(cloudflared)
        .args([
            "tunnel",
            "--protocol",
            "http2",
            // The supervisor reports connectivity changes and recovery itself.
            // cloudflared's info stream repeats per-connection lifecycle details
            // and overwhelms `vestad logs`; retain only actionable diagnostics.
            "--loglevel",
            "warn",
            "--metrics",
            &metrics_addr,
            "--config",
        ])
        .arg(&cf_config_path)
        .args(["run", "--token", &tc.tunnel_token])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::piped())
        // SIGKILL the child if its handle is dropped without an explicit kill
        // (supervisor task aborted, runtime torn down by a panic) so cloudflared
        // is never orphaned holding the hostname.
        .kill_on_drop(true)
        .spawn()
        .map_err(|e| format!("failed to start cloudflared: {e}"))?;

    // Forward cloudflared's remaining warnings/errors into vestad's tracing. This
    // also drains the piped stderr, which would otherwise fill and stall it.
    if let Some(stderr) = child.stderr.take() {
        tokio::spawn(async move {
            use tokio::io::AsyncBufReadExt;
            let mut lines = tokio::io::BufReader::new(stderr).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                let line = line.trim();
                if !line.is_empty() {
                    let (message, is_error) = clean_cloudflared_log(line);
                    if is_error {
                        tracing::error!(target: "tunnel", "{message}");
                    } else {
                        tracing::warn!(target: "tunnel", "{message}");
                    }
                }
            }
        });
    }

    Ok((child, metrics_port))
}

/// cloudflared output varies between plain and JSON across builds. Keep the human
/// message and error detail, and discard connector ids and other metadata when
/// structured output is available.
fn clean_cloudflared_log(line: &str) -> (String, bool) {
    if let Ok(value) = serde_json::from_str::<serde_json::Value>(line) {
        let level = value["level"].as_str().unwrap_or("warn");
        let is_error = matches!(level, "error" | "fatal" | "panic");
        let mut message = value["message"].as_str().unwrap_or(line).to_string();
        if let Some(error) = value["error"].as_str() {
            if !error.is_empty() && !message.contains(error) {
                message.push_str(": ");
                message.push_str(error);
            }
        }
        return (message, is_error);
    }

    let first = line.split_whitespace().next().unwrap_or("");
    let rest = line.strip_prefix(first).unwrap_or(line).trim_start();
    let level = rest.split_whitespace().next().unwrap_or("");
    let normalized_level = level.trim_matches(|c: char| !c.is_ascii_alphabetic());
    let is_cloudflared_level = matches!(
        normalized_level,
        "INF" | "WRN" | "ERR" | "FTL" | "INFO" | "WARN" | "ERROR" | "FATAL"
    );
    let is_error = matches!(normalized_level, "ERR" | "FTL" | "ERROR" | "FATAL");
    let message = if is_cloudflared_level {
        rest.strip_prefix(level).unwrap_or(rest).trim_start()
    } else {
        line
    };
    (message.to_string(), is_error)
}

/// Bind-and-drop an ephemeral loopback port for cloudflared's metrics server.
fn alloc_loopback_port() -> Result<u16, String> {
    let listener = std::net::TcpListener::bind(("127.0.0.1", 0))
        .map_err(|e| format!("failed to allocate metrics port: {e}"))?;
    let addr = listener
        .local_addr()
        .map_err(|e| format!("failed to read metrics port: {e}"))?;
    Ok(addr.port())
}

// --- Tunnel supervision ---
// cloudflared is the one long-running child vestad owns, and a dead tunnel is invisible
// from the inside, so two layers heal it: a process exit respawns after a backoff delay,
// and a wedged process is caught by probing cloudflared's own LOCAL /ready endpoint (a
// public-hostname probe would conflate host DNS/egress or edge incidents with a wedged
// connector and kill a healthy tunnel). The supervisor converges tunnel.json before each
// run (establish_tunnel), recreates a sustained-dead tunnel from BYOK creds
// (repair_tunnel), and never deletes tunnel.json: only explicit user action does.

/// Respawn backoff. A respawn whose run reconnects to the edge (a transient blip
/// on a working tunnel) resets to BASE for prompt recovery; a run that never
/// registers (revoked token, deleted tunnel, resolver still down) doubles the
/// delay up to MAX, so a permanently-failing tunnel settles into a slow retry
/// instead of churning cloudflared every BASE seconds forever. Either way it
/// keeps retrying, so a transient outage of any length still recovers on its own.
const TUNNEL_RESPAWN_BASE_DELAY_SECS: u64 = 15;
/// Capped at the sustained-down window (`TUNNEL_DOWN_SUSTAINED_SECS)`: never wait
/// longer to retry than we wait to declare the tunnel down, so recovery after a
/// long outage lags by at most one down-window rather than several minutes more.
const TUNNEL_RESPAWN_MAX_DELAY_SECS: u64 = 120;
const READY_PROBE_INTERVAL_SECS: u64 = 30;
const READY_PROBE_TIMEOUT_SECS: u64 = 5;
/// Consecutive failed /ready probes before cloudflared is restarted.
const READY_PROBE_MAX_FAILURES: u32 = 3;
/// How long the tunnel must stay unregistered before the supervisor reports it
/// down to status.json. Longer than a normal restart-recovery cycle, so transient
/// blips the supervisor heals on its own keep the status showing "enabled".
const TUNNEL_DOWN_SUSTAINED_SECS: u64 = 120;
/// How long shutdown waits for the supervisor task before aborting it. The
/// task can be inside a blocking Cloudflare API sequence (establish or
/// repair); aborting is safe, cloudflared children are `kill_on_drop` and the
/// curl at worst runs out its own --max-time detached.
const TUNNEL_SHUTDOWN_MAX_WAIT_SECS: u64 = 10;

pub struct TunnelSupervisor {
    shutdown: tokio::sync::watch::Sender<bool>,
    task: tokio::task::JoinHandle<()>,
}

impl TunnelSupervisor {
    /// Kill the current cloudflared and stop supervising (graceful shutdown,
    /// bounded by `TUNNEL_SHUTDOWN_MAX_WAIT_SECS`).
    pub async fn shutdown(self) {
        self.shutdown.send(true).ok();
        let mut task = self.task;
        if tokio::time::timeout(
            std::time::Duration::from_secs(TUNNEL_SHUTDOWN_MAX_WAIT_SECS),
            &mut task,
        )
        .await
        .is_err()
        {
            task.abort();
        }
    }
}

/// Spawn cloudflared and keep it alive until `shutdown()`: respawn on exit or on a
/// failed edge probe streak, after a backoff delay between attempts (see
/// `next_respawn_delay_secs`). `on_tunnel_up(bool)` is invoked on SUSTAINED edge
/// changes (debounced) so the caller can mirror tunnel health into status.json:
/// `true` when the tunnel registers (including the first registration after boot),
/// `false` only after it has been unregistered for `TUNNEL_DOWN_SUSTAINED_SECS`, so
/// transient blips the supervisor heals don't flip status. Kept as a plain
/// `Fn(bool)` to keep this module free of caller types.
pub fn supervise_tunnel(
    config_dir: PathBuf,
    port: u16,
    on_tunnel_up: std::sync::Arc<dyn Fn(bool) + Send + Sync>,
) -> TunnelSupervisor {
    let (shutdown_tx, mut shutdown_rx) = tokio::sync::watch::channel(false);
    let task = tokio::spawn(async move {
        // One client for every probe across respawns. Build failure is
        // near-impossible; if it happens, degrade to exit-only supervision and
        // say so once instead of silently skipping every probe.
        let probe_client = match reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(READY_PROBE_TIMEOUT_SECS))
            .build()
        {
            Ok(client) => Some(client),
            Err(e) => {
                tracing::warn!("tunnel ready probe disabled, supervising exits only: {e}");
                None
            }
        };
        // Edge state for status.json, carried across cloudflared restarts.
        // Nothing is reported at spawn (boot shows "connecting…"), so the first
        // registered probe reports up, and a boot that never registers reports
        // down once the outage is sustained.
        let mut reported: Option<bool> = None;
        let mut last_registered = tokio::time::Instant::now();
        let mut respawn_delay_secs = TUNNEL_RESPAWN_BASE_DELAY_SECS;
        // Latches once a repair (tunnel recreated from scratch) succeeds, so a
        // sustained API-reachable/edge-unreachable incident doesn't recreate the
        // tunnel + DNS every cycle; a run that registers clears it.
        let mut repaired_since_registered = false;
        loop {
            // Establish before each run: an existing tunnel.json is used as-is
            // (subdomain reconciliation is `vestad connect`'s job, never the
            // supervisor's); a missing one is created from BYOK creds; a
            // managed box keeps erroring here until the control plane seeds
            // it. The Cloudflare API call goes through blocking curl, so it
            // runs off the async runtime.
            let ensure_dir = config_dir.clone();
            let attempt = match tokio::task::spawn_blocking(move || establish_tunnel(&ensure_dir))
                .await
                .unwrap_or_else(|join_err| Err(format!("establish_tunnel task failed: {join_err}")))
            {
                Ok(_) => start_tunnel(&config_dir, port),
                Err(e) => Err(e),
            };
            match attempt {
                Ok((mut child, metrics_port)) => {
                    let (reason, registered) = tokio::select! {
                        _ = shutdown_rx.changed() => {
                            child.kill().await.ok();
                            return;
                        }
                        outcome = run_until_unhealthy(
                            &mut child,
                            probe_client.as_ref(),
                            metrics_port,
                            on_tunnel_up.as_ref(),
                            &mut reported,
                            &mut last_registered,
                        ) => outcome,
                    };
                    child.kill().await.ok();
                    respawn_delay_secs = next_respawn_delay_secs(respawn_delay_secs, registered);
                    tracing::warn!(
                        delay_secs = respawn_delay_secs,
                        "tunnel unhealthy ({reason}), restarting cloudflared"
                    );
                    if registered {
                        repaired_since_registered = false;
                    }
                }
                Err(e) => {
                    // Establish or start never reached the edge, so this counts
                    // as a run that did not register — back off.
                    respawn_delay_secs = next_respawn_delay_secs(respawn_delay_secs, false);
                    tracing::warn!(delay_secs = respawn_delay_secs, "tunnel not up: {e}");
                }
            }
            // A cycle that ends without a registered edge (fast cloudflared
            // exit, establish or start failure) never reaches a probe tick, so
            // evaluate the sustained window here too; the report latches via
            // `reported`, firing at most once per sustained outage.
            report_sustained_edge(&mut reported, false, last_registered, on_tunnel_up.as_ref());
            if should_attempt_repair(reported, has_cf_creds(&config_dir), repaired_since_registered)
                && repair_tunnel(&config_dir).await
            {
                repaired_since_registered = true;
                // A fresh tunnel deserves a prompt first run, not the grown
                // failure backoff.
                respawn_delay_secs = TUNNEL_RESPAWN_BASE_DELAY_SECS;
            }
            tokio::select! {
                _ = shutdown_rx.changed() => return,
                () = tokio::time::sleep(std::time::Duration::from_secs(respawn_delay_secs)) => {}
            }
        }
    });
    TunnelSupervisor {
        shutdown: shutdown_tx,
        task,
    }
}

/// Watch one cloudflared run; returns `(reason it must be replaced, whether this
/// run ever registered an edge connection)`. The reason is a process exit or
/// /ready failing `READY_PROBE_MAX_FAILURES` times in a row; the `registered` flag
/// drives the respawn backoff (a run that reconnected resets it, one that never
/// did lets it grow). Drives the debounced `on_tunnel_up` edge callback via
/// `reported`/`last_registered`, which persist across restarts.
async fn run_until_unhealthy(
    child: &mut tokio::process::Child,
    probe_client: Option<&reqwest::Client>,
    metrics_port: u16,
    on_tunnel_up: &(dyn Fn(bool) + Send + Sync),
    reported: &mut Option<bool>,
    last_registered: &mut tokio::time::Instant,
) -> (String, bool) {
    let probe_url = format!("http://127.0.0.1:{metrics_port}/ready");
    let probe_interval = std::time::Duration::from_secs(READY_PROBE_INTERVAL_SECS);
    // First probe only after a full interval, so cloudflared has time to register.
    let mut probe_ticks =
        tokio::time::interval_at(tokio::time::Instant::now() + probe_interval, probe_interval);
    // Don't burst queued ticks after a host suspend/resume: three instant
    // probes would read as a failure streak and kill a tunnel that is still
    // reconnecting on its own.
    probe_ticks.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    let mut consecutive_failures = 0u32;
    // Whether this run ever saw a registered edge connection. Feeds the respawn
    // backoff: a run that reconnected is a transient blip (reset to base), one
    // that never did is a persistent failure (let the delay grow).
    let mut registered = false;
    loop {
        tokio::select! {
            status = child.wait() => {
                let reason = match status {
                    Ok(s) => format!("cloudflared exited: {s}"),
                    Err(e) => format!("cloudflared wait failed: {e}"),
                };
                return (reason, registered);
            }
            _ = probe_ticks.tick() => {
                let Some(client) = probe_client else { continue };
                // /ready is 200 iff cloudflared has a registered edge connection.
                let ok = match client.get(&probe_url).send().await {
                    Ok(resp) => resp.status().is_success(),
                    Err(_) => false,
                };
                if ok {
                    registered = true;
                    *last_registered = tokio::time::Instant::now();
                }
                // Mirror health into status.json on sustained edges only: "up" the
                // moment it registers, "down" only after a sustained outage.
                report_sustained_edge(reported, ok, *last_registered, on_tunnel_up);
                let (failures, restart) = record_probe(consecutive_failures, ok);
                consecutive_failures = failures;
                if !ok {
                    tracing::warn!(consecutive_failures, "tunnel ready probe failed (no registered edge connection)");
                }
                if restart {
                    return (format!("no ready edge connection for {consecutive_failures} consecutive probes"), registered);
                }
            }
        }
    }
}

/// Pure backoff accounting: after a run that registered an edge connection reset
/// to base (recovery should be prompt), otherwise double up to the cap so a
/// persistently-failing tunnel stops churning cloudflared every base delay.
fn next_respawn_delay_secs(current: u64, registered: bool) -> u64 {
    if registered {
        return TUNNEL_RESPAWN_BASE_DELAY_SECS;
    }
    current.saturating_mul(2).min(TUNNEL_RESPAWN_MAX_DELAY_SECS)
}

/// Pure probe accounting: a success clears the failure streak; a failure
/// extends it, demanding a restart at `READY_PROBE_MAX_FAILURES`.
fn record_probe(consecutive_failures: u32, ok: bool) -> (u32, bool) {
    if ok {
        return (0, false);
    }
    let failures = consecutive_failures + 1;
    (failures, failures >= READY_PROBE_MAX_FAILURES)
}

/// Evaluate one health observation against the sustained-down window and report
/// a debounced edge transition at most once (see `edge_report`), latching what
/// was reported into `reported`.
fn report_sustained_edge(
    reported: &mut Option<bool>,
    ok: bool,
    last_registered: tokio::time::Instant,
    on_tunnel_up: &(dyn Fn(bool) + Send + Sync),
) {
    let sustained_down =
        last_registered.elapsed() >= std::time::Duration::from_secs(TUNNEL_DOWN_SUSTAINED_SECS);
    if let Some(report) = edge_report(*reported, ok, sustained_down) {
        on_tunnel_up(report);
        *reported = Some(report);
    }
}

/// Pure edge accounting for status.json: which sustained transition (if any) to
/// report given what was last reported (`None` = nothing yet, at boot). Reports
/// up on the first successful probe after boot or a reported outage; reports
/// down once the edge has been unregistered for the sustained window.
fn edge_report(reported: Option<bool>, ok: bool, sustained_down: bool) -> Option<bool> {
    if ok && reported != Some(true) {
        return Some(true);
    }
    if !ok && sustained_down && reported != Some(false) {
        return Some(false);
    }
    None
}

/// Whether to recreate the tunnel from scratch: only once the outage is
/// sustained enough to have been reported down (a pre-report failure is
/// routinely transient: a boot-time resolver race, a brief edge blip), only
/// with our own Cloudflare creds to rebuild with, and only once per
/// down-period (a run that registers clears the latch).
fn should_attempt_repair(reported: Option<bool>, has_creds: bool, repaired_since_registered: bool) -> bool {
    reported == Some(false) && has_creds && !repaired_since_registered
}

/// Recreate the saved tunnel from scratch (same subdomain, fresh tunnel + token +
/// DNS record) after a run that never registered. During a network outage the
/// API call fails fast and changes nothing; with a live network and a revoked or
/// deleted tunnel this restores it. Never deletes the saved config on failure.
/// Returns true only on a successful recreate, so the caller can latch and stop
/// repairing until a run registers again.
async fn repair_tunnel(config_dir: &Path) -> bool {
    let Some(saved) = get_tunnel_config(config_dir) else {
        return false; // nothing saved yet; the establish step owns creation
    };
    let subdomain = saved.hostname.split('.').next().unwrap_or("").to_string();
    let repair_dir = config_dir.to_path_buf();
    match tokio::task::spawn_blocking(move || setup_tunnel(&repair_dir, &subdomain)).await {
        Ok(Ok(fresh)) => {
            tracing::info!(hostname = %fresh.hostname, "tunnel recreated after a run that never registered");
            true
        }
        Ok(Err(e)) => {
            tracing::warn!("tunnel repair failed: {e}");
            false
        }
        Err(join_err) => {
            tracing::warn!("tunnel repair task failed: {join_err}");
            false
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn provision_keeps_a_saved_tunnel_and_the_credentials_that_made_it() {
        let dir = tempfile::tempdir().expect("tempdir");
        let saved = TunnelConfig {
            tunnel_id: "tunnel-1".to_string(),
            tunnel_token: "tunnel-token".to_string(),
            hostname: "otter.example.com".to_string(),
            dns_record_id: None,
        };
        write_secret_file(
            &tunnel_config_path(dir.path()),
            &serde_json::to_string(&saved).expect("serialize"),
            "tunnel config",
        )
        .expect("write tunnel.json");
        save_cf_creds(dir.path(), &fake_env()).expect("write cloudflare.json");
        let other = CloudflareCreds {
            api_token: "other-token".to_string(),
            ..fake_env()
        };

        let kept = provision_tunnel(dir.path(), &other, None).expect("keeps the saved tunnel");

        assert_eq!(kept.hostname, "otter.example.com");
        assert!(
            cf_env(dir.path()).ok() == Some(fake_env()),
            "cloudflare.json must be unchanged"
        );
    }

    #[test]
    fn a_cloudflare_request_sends_the_bearer_token() {
        use std::io::{BufRead, BufReader, Write};

        let listener = std::net::TcpListener::bind("127.0.0.1:0").expect("bind");
        let url = format!("http://{}/zones", listener.local_addr().expect("addr"));
        let server = std::thread::spawn(move || {
            let (stream, _) = listener.accept().expect("accept");
            let mut reader = BufReader::new(stream.try_clone().expect("clone"));
            let mut headers = Vec::new();
            let mut line = String::new();
            while reader.read_line(&mut line).expect("read") > 0 && line.trim() != "" {
                headers.push(line.trim().to_string());
                line.clear();
            }
            let body = r#"{"success":true,"result":[]}"#;
            write!(
                &stream,
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            )
            .expect("respond");
            headers
        });

        let response = cf_request("GET", &url, "tok-1", None).expect("request succeeds");
        let headers = server.join().expect("server thread");

        assert_eq!(response["success"], true);
        assert!(
            headers.iter().any(|h| h == "Authorization: Bearer tok-1"),
            "{headers:?}"
        );
    }

    fn fake_env() -> CloudflareCreds {
        CloudflareCreds {
            api_token: "token".to_string(),
            account_id: "account".to_string(),
            zone_id: "zone".to_string(),
        }
    }

    /// Which Cloudflare step a call is, by method and path.
    fn cf_step(method: &str, url: &str) -> &'static str {
        match method {
            "DELETE" if url.contains("/dns_records/") => "delete record",
            "DELETE" => "delete tunnel",
            "GET" => "token",
            _ if url.ends_with("/dns_records") => "dns",
            _ => "create",
        }
    }

    /// Run the create sequence against a fake Cloudflare that fails at `fail_at` (a step name or
    /// `persist`); returns the outcome and every step called, in order.
    fn create_with_failure(
        fail_at: Option<&str>,
    ) -> (Result<TunnelConfig, String>, Vec<&'static str>) {
        let env = fake_env();
        let mut steps = Vec::new();
        let result = create_tunnel_records(
            &mut |method, url, _body| {
                let step = cf_step(method, url);
                steps.push(step);
                if fail_at == Some(step) {
                    return Err(format!("{step} refused"));
                }
                Ok(match step {
                    "create" => serde_json::json!({"result": {"id": "tunnel-1"}}),
                    "token" => serde_json::json!({"result": "tunnel-token"}),
                    "dns" => serde_json::json!({"result": {"id": "record-1"}}),
                    _ => serde_json::json!({"result": null}),
                })
            },
            &env,
            "otter",
            "example.com",
            |_config| match fail_at {
                Some("persist") => Err("persist refused".to_string()),
                _ => Ok(()),
            },
        );
        (result, steps)
    }

    #[test]
    fn a_failed_tunnel_setup_deletes_what_it_created() {
        for (fail_at, expected) in [
            ("create", vec!["create"]),
            ("token", vec!["create", "token", "delete tunnel"]),
            ("dns", vec!["create", "token", "dns", "delete tunnel"]),
            (
                "persist",
                vec!["create", "token", "dns", "delete record", "delete tunnel"],
            ),
        ] {
            let (result, steps) = create_with_failure(Some(fail_at));
            let error = result.err().unwrap_or_default();
            assert_eq!(error, format!("{fail_at} refused"), "{fail_at}");
            assert_eq!(steps, expected, "{fail_at}");
        }
    }

    #[test]
    fn a_successful_tunnel_setup_deletes_nothing() {
        let (result, steps) = create_with_failure(None);
        let config = result.expect("setup succeeds");
        assert_eq!(config.hostname, "otter.example.com");
        assert_eq!(config.dns_record_id.as_deref(), Some("record-1"));
        assert_eq!(steps, ["create", "token", "dns"]);
    }

    #[test]
    fn a_failed_rollback_still_reports_the_original_error() {
        let env = fake_env();
        let error = create_tunnel_records(
            &mut |method, url, _body| match cf_step(method, url) {
                "create" => Ok(serde_json::json!({"result": {"id": "tunnel-1"}})),
                step => Err(format!("{step} refused")),
            },
            &env,
            "otter",
            "example.com",
            |_config| Ok(()),
        )
        .err()
        .unwrap_or_default();
        assert_eq!(error, "token refused");
    }

    #[test]
    fn subdomains_must_be_dns_labels() {
        for good in ["otter", "aria-lucio", "a1"] {
            assert!(is_valid_subdomain(good), "{good}");
        }
        for bad in [
            "",
            "-otter",
            "otter-",
            "Otter",
            "ot_ter",
            "ot.ter",
            &"a".repeat(64),
        ] {
            assert!(!is_valid_subdomain(bad), "{bad}");
        }
    }

    #[test]
    fn a_taken_explicit_subdomain_is_an_error_never_a_fallback() {
        let err = choose_subdomain(Some("otter"), "example.com", |_| Ok(true))
            .expect_err("taken name refused");
        assert!(
            err.contains("'otter' is already in use in example.com"),
            "{err}"
        );
    }

    #[test]
    fn a_free_explicit_subdomain_is_used_as_given() {
        let picked = choose_subdomain(Some("otter"), "example.com", |_| Ok(false)).expect("free");
        assert_eq!(picked, "otter");
    }

    #[test]
    fn no_explicit_subdomain_takes_the_first_free_animal() {
        let picked = choose_subdomain(None, "example.com", |_| Ok(false)).expect("free");
        assert_eq!(picked, generate_subdomain(0));
    }

    #[test]
    fn animal_for_user_is_deterministic() {
        let a1 = animal_for_user("alice", 0);
        let a2 = animal_for_user("alice", 0);
        assert_eq!(a1, a2);
    }

    #[test]
    fn animal_offset_changes_result() {
        let a = animal_for_user("alice", 0);
        let b = animal_for_user("alice", 1);
        assert_ne!(a, b, "different offsets should give different animals");
    }

    #[test]
    fn animal_list_is_large_unique_and_dns_safe() {
        const MIN_ANIMALS: usize = 480;
        const MAX_ANIMAL_LEN: usize = 10;
        const DENY: &[&str] = &[
            "ass", "cock", "bitch", "pussy", "booby", "tit", "swine", "pig", "rat", "snake",
            "weasel", "worm", "louse", "leech",
        ];
        assert!(
            ANIMALS.len() >= MIN_ANIMALS,
            "only {} animals",
            ANIMALS.len()
        );
        let mut seen = std::collections::HashSet::new();
        for animal in ANIMALS {
            assert!(seen.insert(animal), "duplicate {animal}");
            assert!(
                (3..=MAX_ANIMAL_LEN).contains(&animal.len()),
                "length of {animal}"
            );
            assert!(
                animal.bytes().all(|b| b.is_ascii_lowercase()),
                "{animal} must be lowercase a-z"
            );
            assert!(!DENY.contains(animal), "{animal} reads as an insult");
        }
    }

    #[test]
    fn cloudflared_json_is_reduced_to_an_actionable_message() {
        let line = r#"{"level":"error","connIndex":2,"message":"connection failed","error":"edge timeout"}"#;
        assert_eq!(
            clean_cloudflared_log(line),
            ("connection failed: edge timeout".to_string(), true)
        );
    }

    #[test]
    fn cloudflared_plain_warnings_keep_their_text_and_severity() {
        let line = "2026-07-23T12:34:56Z WRN reconnecting to edge";
        assert_eq!(
            clean_cloudflared_log(line),
            ("reconnecting to edge".to_string(), false)
        );
    }

    #[test]
    fn cloudflared_plain_errors_are_cleaned_and_promoted() {
        let line = "2026-07-23T12:34:56Z ERR failed to proxy error=\"context canceled\"";
        assert_eq!(
            clean_cloudflared_log(line),
            ("failed to proxy error=\"context canceled\"".to_string(), true)
        );
    }

    #[test]
    fn animal_is_from_list() {
        for name in ["alice", "bob", "root", "deploy", "test-user", "x"] {
            let animal = animal_for_user(name, 0);
            assert!(
                ANIMALS.contains(&animal),
                "{name} mapped to '{animal}' which is not in ANIMALS"
            );
        }
    }

    #[test]
    fn generated_subdomains_are_animals_then_numbered() {
        let first = generate_subdomain(0);
        assert!(
            ANIMALS.contains(&first.as_str()),
            "no hostname suffix: {first}"
        );
        let wrapped = generate_subdomain(ANIMALS.len());
        assert_eq!(wrapped, format!("{first}-2"));
        assert_eq!(generate_subdomain(2 * ANIMALS.len()), format!("{first}-3"));
    }

    #[test]
    fn picker_skips_taken_names() {
        let first = generate_subdomain(0);
        let second = generate_subdomain(1);
        let picked = pick_free_subdomain(|name| Ok(name == first)).expect("a free name");
        assert_eq!(picked, second);
    }

    #[test]
    fn picker_numbers_names_once_every_animal_is_taken() {
        let picked = pick_free_subdomain(|name| Ok(!name.contains('-'))).expect("a free name");
        assert_eq!(picked, format!("{}-2", generate_subdomain(0)));
    }

    #[test]
    fn picker_stops_on_a_failed_check_instead_of_assuming_free() {
        let err =
            pick_free_subdomain(|_| Err("dns read denied".to_string())).expect_err("must fail");
        assert!(err.contains("dns read denied"), "{err}");
    }

    #[test]
    fn boot_keeps_a_saved_tunnel_without_a_pin() {
        let dir = tempfile::tempdir().expect("tempdir");
        let saved = TunnelConfig {
            tunnel_id: "id".to_string(),
            tunnel_token: "token".to_string(),
            hostname: "aria-lucio.example.com".to_string(),
            dns_record_id: Some("rec".to_string()),
        };
        let path = tunnel_config_path(dir.path());
        std::fs::write(&path, serde_json::to_string_pretty(&saved).expect("json")).expect("write");
        let before = std::fs::read_to_string(&path).expect("read");

        let kept = ensure_tunnel_with(dir.path(), None).expect("saved tunnel is used");

        assert_eq!(kept.hostname, saved.hostname);
        assert_eq!(std::fs::read_to_string(&path).expect("read"), before);
    }

    #[test]
    fn boot_keeps_a_saved_tunnel_that_matches_the_pin() {
        let dir = tempfile::tempdir().expect("tempdir");
        let saved = TunnelConfig {
            tunnel_id: "id".to_string(),
            tunnel_token: "token".to_string(),
            hostname: "demo.example.com".to_string(),
            dns_record_id: None,
        };
        std::fs::write(
            tunnel_config_path(dir.path()),
            serde_json::to_string_pretty(&saved).expect("json"),
        )
        .expect("write");
        let kept = ensure_tunnel_with(dir.path(), Some("demo")).expect("pin matches");
        assert_eq!(kept.hostname, "demo.example.com");
    }

    #[test]
    fn sanitize_strips_special_chars() {
        assert_eq!(sanitize("Alice.Bob"), "alice-bob");
        assert_eq!(sanitize("--test--"), "test");
        assert_eq!(sanitize("a_b@c"), "a-b-c");
    }

    #[test]
    fn probe_success_clears_the_failure_streak() {
        assert_eq!(record_probe(READY_PROBE_MAX_FAILURES - 1, true), (0, false));
    }

    #[test]
    fn probe_failures_demand_restart_only_at_threshold() {
        let mut failures = 0;
        for expected in 1..READY_PROBE_MAX_FAILURES {
            let (count, restart) = record_probe(failures, false);
            assert_eq!(count, expected);
            assert!(!restart, "no restart before the threshold");
            failures = count;
        }
        let (count, restart) = record_probe(failures, false);
        assert_eq!(count, READY_PROBE_MAX_FAILURES);
        assert!(restart, "restart at the threshold");
    }

    #[test]
    fn edge_report_reports_each_sustained_transition_once() {
        // Boot, nothing reported yet: first success reports up.
        assert_eq!(edge_report(None, true, false), Some(true));
        // Already up: further successes are silent.
        assert_eq!(edge_report(Some(true), true, false), None);
        // Up, blip not yet sustained: silent.
        assert_eq!(edge_report(Some(true), false, false), None);
        // Up, outage sustained: reports down once.
        assert_eq!(edge_report(Some(true), false, true), Some(false));
        assert_eq!(edge_report(Some(false), false, true), None);
        // Down, recovers: reports up.
        assert_eq!(edge_report(Some(false), true, false), Some(true));
        // Boot, never registers, sustained: reports down so status.json gets
        // the recovery hint instead of showing connecting forever.
        assert_eq!(edge_report(None, false, true), Some(false));
        // Boot, not yet sustained: silent.
        assert_eq!(edge_report(None, false, false), None);
    }

    #[test]
    fn repair_waits_for_a_reported_sustained_outage_and_runs_once() {
        // Reported down, holding our own creds, no prior repair this
        // down-period: repair.
        assert!(should_attempt_repair(Some(false), true, false));
        // A repair already succeeded this down-period: don't recreate again
        // every cycle while the outage continues.
        assert!(!should_attempt_repair(Some(false), true, true));
        // No creds (managed / legacy): nothing to rebuild with.
        assert!(!should_attempt_repair(Some(false), false, false));
        // Reported up: the tunnel is fine, nothing to repair.
        assert!(!should_attempt_repair(Some(true), true, false));
        // Not yet reported down (a pre-report failure is routinely
        // transient): wait for the sustained-outage report before repairing.
        assert!(!should_attempt_repair(None, true, false));
    }

    #[test]
    fn respawn_backoff_grows_to_cap_while_failing_and_resets_on_reconnect() {
        // A persistently-failing tunnel doubles the delay from base up to the cap
        // and then stays there — no unbounded growth, no churn past the ceiling.
        let mut delay = TUNNEL_RESPAWN_BASE_DELAY_SECS;
        let mut seen = vec![delay];
        for _ in 0..8 {
            delay = next_respawn_delay_secs(delay, false);
            seen.push(delay);
        }
        assert_eq!(seen[0], TUNNEL_RESPAWN_BASE_DELAY_SECS);
        assert_eq!(seen[1], TUNNEL_RESPAWN_BASE_DELAY_SECS * 2);
        assert_eq!(*seen.last().unwrap(), TUNNEL_RESPAWN_MAX_DELAY_SECS);
        assert!(
            seen.windows(2).all(|w| w[1] >= w[0]),
            "delay is monotonic while failing"
        );
        assert!(
            seen.iter().all(|&d| d <= TUNNEL_RESPAWN_MAX_DELAY_SECS),
            "never exceeds the cap"
        );

        // A run that reconnected resets straight to base, however large the delay had grown.
        assert_eq!(
            next_respawn_delay_secs(TUNNEL_RESPAWN_MAX_DELAY_SECS, true),
            TUNNEL_RESPAWN_BASE_DELAY_SECS
        );
    }

    #[test]
    fn alloc_loopback_port_returns_a_usable_port() {
        let port = alloc_loopback_port().expect("allocation succeeds");
        assert_ne!(port, 0);
    }

    #[test]
    fn supervisor_establish_never_rewrites_an_existing_config() {
        let dir = tempfile::tempdir().expect("tempdir");
        // A saved config whose subdomain does NOT match preferred_subdomain()
        // (simulates legacy creds-less box / hostname drift): the supervisor
        // must use it as-is, never destroy or recreate it.
        let mismatched = TunnelConfig {
            tunnel_id: "existing-tunnel-id".to_string(),
            tunnel_token: "existing-token".to_string(),
            hostname: "definitely-not-preferred.example.com".to_string(),
            dns_record_id: Some("existing-record-id".to_string()),
        };
        let path = tunnel_config_path(dir.path());
        std::fs::write(&path, serde_json::to_string_pretty(&mismatched).unwrap())
            .expect("write tunnel.json");
        let original_contents = std::fs::read_to_string(&path).expect("read back");

        let result = establish_tunnel(dir.path()).expect("establish succeeds from saved config");

        assert_eq!(result.hostname, mismatched.hostname);
        assert_eq!(result.tunnel_id, mismatched.tunnel_id);
        assert!(path.exists(), "tunnel.json must still exist");
        assert_eq!(
            std::fs::read_to_string(&path).expect("read back after establish"),
            original_contents,
            "tunnel.json content must be unchanged"
        );
    }

    #[test]
    fn establish_tunnel_errors_when_the_user_declined_and_nothing_is_saved() {
        let dir = tempfile::tempdir().expect("tempdir");
        std::fs::write(no_tunnel_marker_path(dir.path()), "").expect("write no_tunnel marker");

        let err = match establish_tunnel(dir.path()) {
            Err(e) => e,
            Ok(_) => panic!("a declined tunnel must not be established"),
        };

        assert!(err.contains("declined"), "error should mention the decline: {err}");
    }

    #[test]
    fn ensure_tunnel_keeps_the_saved_config_when_reconcile_fails_without_creds() {
        let dir = tempfile::tempdir().expect("tempdir");
        // A saved config whose subdomain does NOT match the pin, and no
        // cloudflare.json / CLOUDFLARE_* env: the reconcile attempt fails at
        // cf_env before any curl, so it must never touch the saved tunnel.json.
        let preferred = generate_subdomain(0);
        let stale = TunnelConfig {
            tunnel_id: "stale-tunnel-id".to_string(),
            tunnel_token: "stale-token".to_string(),
            hostname: format!("{preferred}-stale.example.com"),
            dns_record_id: Some("stale-record-id".to_string()),
        };
        let path = tunnel_config_path(dir.path());
        std::fs::write(&path, serde_json::to_string_pretty(&stale).unwrap())
            .expect("write tunnel.json");
        let original_contents = std::fs::read_to_string(&path).expect("read back");

        let result = ensure_tunnel_with(dir.path(), Some(&format!("{preferred}-other")));

        assert!(
            result.is_err(),
            "no cloudflare.json and no CLOUDFLARE_* env: reconcile cannot succeed"
        );
        assert!(path.exists(), "tunnel.json must still exist after a failed reconcile");
        assert_eq!(
            std::fs::read_to_string(&path).expect("read back after ensure_tunnel"),
            original_contents,
            "tunnel.json content must be unchanged"
        );
    }
}
