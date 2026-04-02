#!/usr/bin/env node
import { BrowserClaw, findFreePort } from './dist/index.js';
import { readFileSync, writeFileSync, mkdirSync, unlinkSync, readdirSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';
import { execSync } from 'child_process';

// ── Paths ──

const SESSION_DIR = join(homedir(), '.browser');

// Session file resolution:
// - BROWSER_SESSION env var: explicit session file name for multi-agent isolation
//   Each subagent sets a unique value (e.g. "agent-1", "agent-2") to get its own session.
// - Default: 'session.json' (backwards compatible with single-agent use)
function sessionFileName() {
  const id = process.env.BROWSER_SESSION;
  if (id) return `session-${id}.json`;
  return 'session.json';
}
const SESSION_FILE = join(SESSION_DIR, sessionFileName());

// ── Output ──

function out(obj) {
  process.stdout.write(JSON.stringify(obj, null, 2) + '\n');
}

function fail(msg) {
  process.stderr.write(JSON.stringify({ error: String(msg) }) + '\n');
  process.exit(1);
}

// ── Session ──

function readSession() {
  try {
    return JSON.parse(readFileSync(SESSION_FILE, 'utf8'));
  } catch {
    return null;
  }
}

function writeSession(cdpUrl, pid, stealth = false) {
  mkdirSync(SESSION_DIR, { recursive: true });
  writeFileSync(SESSION_FILE, JSON.stringify({ cdpUrl, pid, stealth, launchedAt: new Date().toISOString() }));
}

function clearSession() {
  try { unlinkSync(SESSION_FILE); } catch {}
}

function isStealth() {
  const session = readSession();
  return session?.stealth === true;
}

async function connect() {
  const session = readSession();
  if (!session) fail('No browser session. Run: browser launch');
  try {
    return await BrowserClaw.connect(session.cdpUrl);
  } catch {
    clearSession();
    fail('Browser session expired or crashed. Run: browser launch');
  }
}

async function currentPage(browser) {
  try {
    return await browser.currentPage();
  } catch {
    fail('No open tabs. Run: browser open <url>');
  }
}

// ── Cloudflare Solving ──

const CF_IFRAME_PATTERN = /^https?:\/\/challenges\.cloudflare\.com\/cdn-cgi\/challenge-platform\/.*/;

async function solveCloudflare(page) {
  const title = await page.title();
  if (title !== 'Just a moment...') return true;

  const html = await page.evaluate('() => document.documentElement.innerHTML');

  // Non-interactive challenge (auto-resolve)
  if (!html.includes('Verifying you are human') && !html.toLowerCase().includes('turnstile')) {
    const deadline = Date.now() + 30000;
    while (Date.now() < deadline) {
      if (await page.title() !== 'Just a moment...') return true;
      await new Promise(r => setTimeout(r, 1000));
    }
    return false;
  }

  // Wait for verify spinner to pass
  const spinnerDeadline = Date.now() + 10000;
  while (Date.now() < spinnerDeadline) {
    const h = await page.evaluate('() => document.documentElement.innerHTML');
    if (!h.includes('Verifying you are human')) break;
    await new Promise(r => setTimeout(r, 500));
  }

  // Find and click the CF Turnstile iframe checkbox
  // Use evaluateInAllFrames to find the CF challenge iframe and get its bounding box,
  // then use evaluate to dispatch a click at the right coordinates.
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      // Find CF iframe bounding box via top-level evaluate
      const box = await page.evaluate(`() => {
        const iframes = document.querySelectorAll('iframe');
        for (const iframe of iframes) {
          if (/challenges\\.cloudflare\\.com\\/cdn-cgi\\/challenge-platform/.test(iframe.src || '')) {
            const rect = iframe.getBoundingClientRect();
            return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
          }
        }
        return null;
      }`);

      if (box) {
        // Click at the checkbox position within the iframe (offset ~26, ~25 from top-left)
        const x = box.x + 26 + Math.random() * 2;
        const y = box.y + 25 + Math.random() * 2;
        await page.evaluate(`() => {
          const el = document.elementFromPoint(${x}, ${y});
          if (el) el.click();
        }`);
        await new Promise(r => setTimeout(r, 3000));
      }
    } catch {}

    if (await page.title() !== 'Just a moment...') return true;
    await new Promise(r => setTimeout(r, 2000));
  }

  return await page.title() !== 'Just a moment...';
}

// ── Stealth Helpers ──

function generateReferer(url) {
  try {
    const domain = new URL(url).hostname.replace(/^www\./, '');
    return `https://www.google.com/search?q=${domain}`;
  } catch {
    return undefined;
  }
}

// ── Arg Parsing ──

function parseArgs(argv) {
  const positionals = [];
  const flags = {};
  let i = 0;
  while (i < argv.length) {
    const arg = argv[i];
    if (arg.startsWith('--')) {
      const key = arg.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith('--')) {
        flags[key] = true;
        i++;
      } else {
        flags[key] = next;
        i += 2;
      }
    } else {
      positionals.push(arg);
      i++;
    }
  }
  return { positionals, flags };
}

// ── Commands ──

async function cmdLaunch(args) {
  const existing = readSession();
  if (existing) {
    try {
      const b = await BrowserClaw.connect(existing.cdpUrl);
      await b.stop();
    } catch {}
    if (existing.pid) {
      try { process.kill(existing.pid, 'SIGTERM'); } catch {}
    }
    clearSession();
  }

  const inDocker = process.env.IS_SANDBOX === '1';
  const stealth = Boolean(args.flags.stealth);
  const headless = args.flags.headless !== undefined ? Boolean(args.flags.headless) : inDocker;
  const userDataDir = args.flags['user-data-dir'] || join(SESSION_DIR, 'profile');

  // Port resolution:
  // 1. --port flag: use exactly that port (explicit override)
  // 2. No --port: auto-find a free port starting from 9222
  //    This allows multiple subagents to each get their own Chrome instance.
  let port;
  if (args.flags.port) {
    port = Number(args.flags.port);
  } else {
    try {
      port = await findFreePort(9222, 100);
    } catch (e) {
      fail(`Could not find a free port for Chrome: ${e.message}`);
    }
  }

  const chromeArgs = [];
  if (args.flags.proxy) chromeArgs.push(`--proxy-server=${args.flags.proxy}`);

  const browser = await BrowserClaw.launch({
    headless,
    cdpPort: port,
    noSandbox: inDocker,
    userDataDir,
    stealth,
    chromeArgs: chromeArgs.length ? chromeArgs : undefined,
  });

  writeSession(browser.url, browser.pid, stealth);
  out({ status: 'launched', cdpUrl: browser.url, pid: browser.pid, headless, stealth, port });
  process.exit(0);
}

async function cmdSessions() {
  mkdirSync(SESSION_DIR, { recursive: true });
  const files = readdirSync(SESSION_DIR).filter(f => f.startsWith('session') && f.endsWith('.json'));
  const sessions = [];
  for (const file of files) {
    try {
      const data = JSON.parse(readFileSync(join(SESSION_DIR, file), 'utf8'));
      let alive = false;
      if (data.pid) {
        try { process.kill(data.pid, 0); alive = true; } catch {}
      }
      sessions.push({ file, ...data, alive });
    } catch {}
  }
  out({ sessions });
}

async function cmdStopAll() {
  mkdirSync(SESSION_DIR, { recursive: true });
  const files = readdirSync(SESSION_DIR).filter(f => f.startsWith('session') && f.endsWith('.json'));
  const stopped = [];
  for (const file of files) {
    try {
      const data = JSON.parse(readFileSync(join(SESSION_DIR, file), 'utf8'));
      if (data.cdpUrl) {
        try {
          const b = await BrowserClaw.connect(data.cdpUrl);
          await b.stop();
        } catch {}
      }
      if (data.pid) {
        try { process.kill(data.pid, 'SIGTERM'); } catch {}
      }
      try { unlinkSync(join(SESSION_DIR, file)); } catch {}
      stopped.push(file);
    } catch {}
  }
  out({ status: 'stopped_all', stopped });
}

async function cmdConnect(args) {
  const cdpUrl = args.positionals[0] || 'http://localhost:9222';

  const existing = readSession();
  if (existing) {
    try {
      const b = await BrowserClaw.connect(existing.cdpUrl);
      await b.stop();
    } catch {}
    clearSession();
  }

  const browser = await BrowserClaw.connect(cdpUrl);
  const tabs = await browser.tabs();
  writeSession(cdpUrl, null);
  out({ status: 'connected', cdpUrl, tabs: tabs.length });
  process.exit(0);
}

async function cmdStop() {
  const session = readSession();
  if (!session) fail('No browser session to stop.');

  try {
    const browser = await BrowserClaw.connect(session.cdpUrl);
    await browser.stop();
  } catch {}

  // Only kill local processes (remote sessions have no local PID)
  if (session.pid) {
    try { process.kill(session.pid, 'SIGTERM'); } catch {}
  }

  clearSession();
  out({ status: 'stopped' });
}

async function cmdTabs() {
  const browser = await connect();
  const tabs = await browser.tabs();
  out({ tabs });
}

async function cmdOpen(args) {
  const url = args.positionals[0];
  if (!url) fail('Usage: browser open <url>');
  const browser = await connect();
  const page = await browser.open(url);
  if (isStealth() && !args.flags['no-cf-solve']) {
    await solveCloudflare(page);
  }
  const snap = await page.snapshot(snapshotOpts());
  out({
    tabId: page.id,
    url: await page.url(),
    title: await page.title(),
    snapshot: snap.snapshot,
    stats: snap.stats,
  });
}

async function cmdNavigate(args) {
  const url = args.positionals[0];
  if (!url) fail('Usage: browser navigate <url>');
  const browser = await connect();
  const page = await currentPage(browser);
  await page.goto(url);
  if (isStealth() && !args.flags['no-cf-solve']) {
    await solveCloudflare(page);
  }
  const snap = await page.snapshot(snapshotOpts());
  out({
    url: await page.url(),
    title: await page.title(),
    snapshot: snap.snapshot,
    stats: snap.stats,
  });
}

async function cmdFocus(args) {
  const tabId = args.positionals[0];
  if (!tabId) fail('Usage: browser focus <tabId>');
  const browser = await connect();
  await browser.focus(tabId);
  out({ status: 'focused', tabId });
}

async function cmdClose(args) {
  const tabId = args.positionals[0];
  if (!tabId) fail('Usage: browser close <tabId>');
  const browser = await connect();
  await browser.close(tabId);
  out({ status: 'closed', tabId });
}

// Default max chars for snapshots to prevent overwhelming output on complex pages.
// Can be overridden with --max-chars flag or BROWSER_MAX_CHARS env var.
const DEFAULT_MAX_CHARS = Number(process.env.BROWSER_MAX_CHARS) || 50000;

function snapshotOpts(extra = {}) {
  return { interactive: true, maxChars: DEFAULT_MAX_CHARS, ...extra };
}

async function cmdSnapshot(args) {
  const browser = await connect();
  const page = await currentPage(browser);
  const opts = {};
  if (args.flags.interactive) opts.interactive = true;
  if (args.flags.compact) opts.compact = true;
  if (args.flags.mode) opts.mode = args.flags.mode;
  if (args.flags['max-depth']) opts.maxDepth = Number(args.flags['max-depth']);
  opts.maxChars = args.flags['max-chars'] ? Number(args.flags['max-chars']) : DEFAULT_MAX_CHARS;
  const result = await page.snapshot(opts);
  out({
    snapshot: result.snapshot,
    stats: result.stats,
    url: await page.url(),
    title: await page.title(),
  });
}

async function cmdScreenshot(args) {
  const savePath = args.flags.path || '/tmp/screenshot.png';
  const browser = await connect();
  const page = await currentPage(browser);
  const buffer = await page.screenshot({
    fullPage: Boolean(args.flags['full-page']),
  });
  writeFileSync(savePath, buffer);
  out({ status: 'saved', path: savePath });
}

async function cmdClick(args) {
  const ref = args.positionals[0];
  if (!ref) fail('Usage: browser click <ref>');
  const browser = await connect();
  const page = await currentPage(browser);
  // populate ref map
  await page.snapshot();
  const opts = {};
  if (args.flags.double) opts.doubleClick = true;
  if (args.flags.right) opts.button = 'right';
  await page.click(ref, opts);
  const snap = await page.snapshot(snapshotOpts());
  out({
    status: 'clicked',
    ref,
    snapshot: snap.snapshot,
    stats: snap.stats,
    url: await page.url(),
  });
}

async function cmdType(args) {
  const ref = args.positionals[0];
  const text = args.positionals.slice(1).join(' ');
  if (!ref || !text) fail('Usage: browser type <ref> <text>');
  const browser = await connect();
  const page = await currentPage(browser);
  await page.snapshot();
  const opts = {};
  if (args.flags.submit) opts.submit = true;
  if (args.flags.slowly) opts.slowly = true;
  await page.type(ref, text, opts);
  const snap = await page.snapshot(snapshotOpts());
  out({
    status: 'typed',
    ref,
    snapshot: snap.snapshot,
    stats: snap.stats,
    url: await page.url(),
  });
}

async function cmdHover(args) {
  const ref = args.positionals[0];
  if (!ref) fail('Usage: browser hover <ref>');
  const browser = await connect();
  const page = await currentPage(browser);
  await page.snapshot();
  await page.hover(ref);
  const snap = await page.snapshot(snapshotOpts());
  out({ status: 'hovered', ref, snapshot: snap.snapshot, stats: snap.stats });
}

async function cmdSelect(args) {
  const ref = args.positionals[0];
  const values = args.positionals.slice(1);
  if (!ref || !values.length) fail('Usage: browser select <ref> <value...>');
  const browser = await connect();
  const page = await currentPage(browser);
  await page.snapshot();
  await page.select(ref, ...values);
  const snap = await page.snapshot(snapshotOpts());
  out({ status: 'selected', ref, values, snapshot: snap.snapshot, stats: snap.stats });
}

async function cmdDrag(args) {
  const from = args.positionals[0];
  const to = args.positionals[1];
  if (!from || !to) fail('Usage: browser drag <fromRef> <toRef>');
  const browser = await connect();
  const page = await currentPage(browser);
  await page.snapshot();
  await page.drag(from, to);
  const snap = await page.snapshot(snapshotOpts());
  out({ status: 'dragged', from, to, snapshot: snap.snapshot, stats: snap.stats });
}

async function cmdFill(args) {
  const json = args.positionals[0];
  if (!json) fail('Usage: browser fill \'[{"ref":"e1","type":"text","value":"hello"}]\'');
  let fields;
  try { fields = JSON.parse(json); } catch { fail('Invalid JSON for fill fields'); }
  const browser = await connect();
  const page = await currentPage(browser);
  await page.snapshot();
  await page.fill(fields);
  const snap = await page.snapshot(snapshotOpts());
  out({ status: 'filled', count: fields.length, snapshot: snap.snapshot, stats: snap.stats });
}

async function cmdPress(args) {
  const key = args.positionals[0];
  if (!key) fail('Usage: browser press <key>');
  const browser = await connect();
  const page = await currentPage(browser);
  await page.press(key);
  const snap = await page.snapshot(snapshotOpts());
  out({ status: 'pressed', key, snapshot: snap.snapshot, stats: snap.stats });
}

async function cmdScroll(args) {
  const ref = args.positionals[0];
  const browser = await connect();
  const page = await currentPage(browser);
  if (ref) {
    await page.snapshot();
    await page.scrollIntoView(ref);
    const snap = await page.snapshot(snapshotOpts());
    out({ status: 'scrolled', ref, snapshot: snap.snapshot, stats: snap.stats });
  } else {
    const direction = args.flags.up ? 'up' : 'down';
    const amount = Number(args.flags.up || args.flags.down || 500);
    const delta = direction === 'up' ? -amount : amount;
    await page.evaluate(`() => window.scrollBy(0, ${delta})`);
    const snap = await page.snapshot(snapshotOpts());
    out({ status: 'scrolled', direction, amount, snapshot: snap.snapshot, stats: snap.stats });
  }
}

async function cmdWait(args) {
  const browser = await connect();
  const page = await currentPage(browser);
  const opts = {};
  if (args.flags.text) opts.text = args.flags.text;
  if (args.flags['text-gone']) opts.textGone = args.flags['text-gone'];
  if (args.flags.url) opts.url = args.flags.url;
  if (args.flags.selector) opts.selector = args.flags.selector;
  if (args.flags.time) opts.timeMs = Number(args.flags.time);
  if (args.flags.timeout) opts.timeoutMs = Number(args.flags.timeout);
  if (args.flags['load-state']) opts.loadState = args.flags['load-state'];
  await page.waitFor(opts);
  const snap = await page.snapshot(snapshotOpts());
  out({ status: 'done', snapshot: snap.snapshot, stats: snap.stats, url: await page.url() });
}

async function cmdEvaluate(args) {
  const expr = args.positionals.join(' ');
  if (!expr) fail('Usage: browser evaluate <js-expression>');
  const browser = await connect();
  const page = await currentPage(browser);
  const result = await page.evaluate(expr);
  out({ result });
}

async function cmdReload() {
  const browser = await connect();
  const page = await currentPage(browser);
  await page.reload();
  const snap = await page.snapshot(snapshotOpts());
  out({ status: 'reloaded', snapshot: snap.snapshot, stats: snap.stats, url: await page.url() });
}

async function cmdBack() {
  const browser = await connect();
  const page = await currentPage(browser);
  await page.goBack();
  const snap = await page.snapshot(snapshotOpts());
  out({ status: 'navigated_back', snapshot: snap.snapshot, stats: snap.stats, url: await page.url() });
}

async function cmdForward() {
  const browser = await connect();
  const page = await currentPage(browser);
  await page.goForward();
  const snap = await page.snapshot(snapshotOpts());
  out({ status: 'navigated_forward', snapshot: snap.snapshot, stats: snap.stats, url: await page.url() });
}

async function cmdDownload(args) {
  const ref = args.positionals[0];
  const savePath = args.positionals[1] || args.flags.path || '/tmp/download';
  if (!ref) fail('Usage: browser download <ref> [path]');
  const browser = await connect();
  const page = await currentPage(browser);
  await page.snapshot();
  const result = await page.download(ref, savePath);
  out({ status: 'downloaded', url: result.url, filename: result.suggestedFilename, path: result.path });
}

async function cmdPdf(args) {
  const savePath = args.flags.path || '/tmp/page.pdf';
  const browser = await connect();
  const page = await currentPage(browser);
  const buffer = await page.pdf();
  writeFileSync(savePath, buffer);
  out({ status: 'saved', path: savePath });
}

async function cmdResize(args) {
  const width = Number(args.positionals[0]);
  const height = Number(args.positionals[1]);
  if (!width || !height) fail('Usage: browser resize <width> <height>');
  const browser = await connect();
  const page = await currentPage(browser);
  await page.resize(width, height);
  out({ status: 'resized', width, height });
}

// ── Dispatch ──

const COMMANDS = {
  launch: cmdLaunch,
  connect: cmdConnect,
  stop: cmdStop,
  'stop-all': cmdStopAll,
  sessions: cmdSessions,
  tabs: cmdTabs,
  open: cmdOpen,
  navigate: cmdNavigate,
  goto: cmdNavigate,
  focus: cmdFocus,
  close: cmdClose,
  snapshot: cmdSnapshot,
  screenshot: cmdScreenshot,
  click: cmdClick,
  type: cmdType,
  hover: cmdHover,
  select: cmdSelect,
  drag: cmdDrag,
  fill: cmdFill,
  press: cmdPress,
  scroll: cmdScroll,
  wait: cmdWait,
  evaluate: cmdEvaluate,
  reload: cmdReload,
  back: cmdBack,
  forward: cmdForward,
  download: cmdDownload,
  pdf: cmdPdf,
  resize: cmdResize,
};

const command = process.argv[2];
if (!command || !COMMANDS[command]) {
  const cmds = Object.keys(COMMANDS).join(', ');
  fail(`Usage: browser <command> [args]\nCommands: ${cmds}`);
}

const args = parseArgs(process.argv.slice(3));
COMMANDS[command](args).then(() => process.exit(0)).catch(e => fail(e.message));
