#!/usr/bin/env python3
"""Exercise the daemon watchdog against synthetic daemons, without touching a real one.

Run: python3 ~/agent/skills/daemon-watchdog/test-watchdog.py

It lives HERE, not in /tmp, because the first version of this suite was written to /tmp and deleted
in the same hour. A test that exists only in a scratch directory runs exactly once, which is the
same failure as a guard nothing invokes: it looks like coverage and is not.

Each case stands up a fake `<name> daemon status|start` on PATH and points the watchdog at a
synthetic daemons.sh. Case 4 is the control: it proves a healthy daemon produces NO notification, so
the failing cases mean the watchdog reads the daemon rather than always complaining.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys

WD = str(pathlib.Path(__file__).with_name("daemon-watchdog"))
TMP = pathlib.Path("/tmp/wd-test")


def fresh():
    if TMP.exists():
        shutil.rmtree(TMP)
    (TMP / "bin").mkdir(parents=True)
    (TMP / "notify").mkdir(parents=True)


def fake_daemon(name, status_json, start_rc=0, start_out='{"status": "started"}'):
    p = TMP / "bin" / name
    p.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "daemon" ] && [ "$2" = "status" ]; then\n'
        f"  cat {TMP}/{name}.status\n  exit 0\nfi\n"
        'if [ "$1" = "daemon" ] && [ "$2" = "start" ]; then\n'
        # Records that a start was ASKED FOR. Without this marker the "restarts nothing" control
        # passes whether or not the code restarts, which makes it decoration.
        f"  touch {TMP}/{name}.started\n"
        f"  echo '{start_out}'\n  exit {start_rc}\nfi\nexit 9\n"
    )
    p.chmod(0o755)
    (TMP / f"{name}.status").write_text(status_json)


def run(lines):
    (TMP / "daemons.sh").write_text("\n".join(lines) + "\n")
    env = dict(
        os.environ,
        PATH=f"{TMP}/bin:" + os.environ["PATH"],
        WATCHDOG_LIST=str(TMP / "daemons.sh"),
        # Without this the unlisted-daemon check reads the REAL pidfile store and reports
        # every daemon on the box as missing from the synthetic list under test.
        WATCHDOG_DAEMONS_DIR=str(TMP / "daemons"),
        WATCHDOG_NOTIFY_DIR=str(TMP / "notify"),
        WATCHDOG_STATE=str(TMP / "state.json"),
        WATCHDOG_HEARTBEAT=str(TMP / "beat"),
        WATCHDOG_DEATHS=str(TMP / "deaths.tsv"),
        WATCHDOG_STATUS_TIMEOUT_SECS="3",
        WATCHDOG_START_TIMEOUT_SECS="3",
    )
    p = subprocess.run([sys.executable, WD, "check"], capture_output=True, text=True, env=env, check=False)
    notes = sorted((TMP / "notify").glob("*.json"))
    return p.returncode, (p.stdout + p.stderr).strip(), [json.loads(n.read_text()) for n in notes]


results = []


def check(name, ok, detail=""):
    print(f"{name:<52} {'PASS' if ok else 'FAIL'}")
    if not ok and detail:
        print("   " + detail.replace("\n", "\n   "))
    results.append(ok)


fresh()
fake_daemon("alpha", '{"running": true, "port": 1}')
code, out, notes = run(["alpha daemon start"])
check("healthy box -> no notification, exit 0", code == 0 and not notes and "all 1 daemons running" in out, f"exit={code} out={out}")

fresh()
fake_daemon("dashboard", '{"running": false, "port": null}')
code, out, notes = run(["dashboard daemon start"])
check(
    "dead daemon -> notified, interrupting, exit 1",
    code == 1 and len(notes) == 1 and notes[0]["daemon"] == "dashboard" and notes[0]["type"] == "daemon_down" and notes[0]["interrupt"] is True,
    f"exit={code} notes={json.dumps(notes)[:300]}",
)

# The whole point of the notify-only shape: a death is REPORTED and the daemon is left exactly as it
# died, so the state the cause is visible in survives for whoever reads the notification.
fresh()
fake_daemon("gamma", '{"running": false}')
code, out, notes = run(["gamma daemon start"])
started = (TMP / "gamma.started").exists()
check(
    "control: a death triggers NO start attempt",
    not started and len(notes) == 1,
    f"start_attempted={started} notes={len(notes)}",
)

fresh()
fake_daemon("dashboard", '{"running": true, "port": 5}')
code, out, notes = run(["dashboard daemon start"])
check("control: healthy dashboard must NOT notify", code == 0 and not notes, f"notes={len(notes)}")

fresh()
fake_daemon("beta", '{"running": false}')
run(["beta daemon start"])
code, out, notes = run(["beta daemon start"])
check("still down -> throttled, no duplicate", len(notes) == 1, f"notes={len(notes)}")

fresh()
fake_daemon("gamma", '{"running": false}')
run(["gamma daemon start"])
(TMP / "gamma.status").write_text('{"running": true}')
run(["gamma daemon start"])
(TMP / "gamma.status").write_text('{"running": false}')
code, out, notes = run(["gamma daemon start"])
check("recovers then dies again -> notifies again", len(notes) == 2, f"notes={len(notes)}")

fresh()
code, out, notes = run(["something-else serve --forever"])
# Unmeasured is never restarted and never reported as down. But when EVERY daemon is unmeasured the
# box cannot be asked anything at all, and silence there is worse than a wrong alarm, because an
# unmeasured daemon writes no notification of its own. So one alarm, typed for what it actually is.
check(
    "all unmeasured -> one unaskable alarm, not daemon_down",
    len(notes) == 1 and notes[0]["type"] == "daemons_unaskable",
    f"out={out} types={[n['type'] for n in notes]}",
)

# The control that makes the assertion above mean something: with one measurable daemon present,
# the box CAN be asked, so an unmeasured sibling must stay quiet rather than raise the same alarm.
fresh()
fake_daemon("gamma", '{"running": true}')
code, out, notes = run(["gamma daemon start", "something-else serve --forever"])
check("control: one unmeasured among healthy -> silent", code == 0 and not notes, f"out={out} notes={len(notes)}")

# --- a list that lost a line, which every other probe on this box cannot see ------------------
# These read the pidfile store, which `daemon start` writes without consulting the list, so they are
# the one check here whose expected set does not come from the file it is auditing.


def pidfile(name, pid):
    d = TMP / "daemons"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.pid").write_text(str(pid))


fresh()
fake_daemon("gamma", '{"running": true}')
pidfile("gamma", os.getpid())
code, out, notes = run(["gamma daemon start"])
check("listed and running -> no unlisted alarm", code == 0 and not notes, f"out={out}")

fresh()
fake_daemon("gamma", '{"running": true}')
pidfile("gamma", os.getpid())
pidfile("delta", os.getpid())
code, out, notes = run(["gamma daemon start"])
check(
    "running but unlisted -> named, non-interrupting",
    len(notes) == 1 and notes[0]["type"] == "daemons_unlisted" and notes[0]["unlisted"] == ["delta"] and notes[0]["interrupt"] is False,
    f"notes={[(n['type'], n.get('unlisted')) for n in notes]}",
)

# The case that keeps this from being a high-water mark on the daemon count: a daemon retired on
# purpose is stopped as well as unlisted, so its pid is dead and there is nothing to report.
fresh()
fake_daemon("gamma", '{"running": true}')
pidfile("gamma", os.getpid())
pidfile("retired", 999999)
code, out, notes = run(["gamma daemon start"])
check("control: unlisted AND stopped -> silent", code == 0 and not notes, f"out={out}")

# An absent list is a box that has registered no daemons yet, which the restart skill calls normal.
# Alarming on it would cry wolf forever upstream. The dangerous version is not silent either way.
fresh()
fake_daemon("gamma", '{"running": true}')
pidfile("gamma", os.getpid())
env_missing = dict(
    os.environ,
    PATH=f"{TMP}/bin:" + os.environ["PATH"],
    WATCHDOG_LIST=str(TMP / "no-such-list.sh"),
    WATCHDOG_DAEMONS_DIR=str(TMP / "daemons"),
    WATCHDOG_NOTIFY_DIR=str(TMP / "notify"),
    WATCHDOG_STATE=str(TMP / "state.json"),
    WATCHDOG_HEARTBEAT=str(TMP / "beat"),
    WATCHDOG_DEATHS=str(TMP / "deaths.tsv"),
)
r = subprocess.run([sys.executable, WD, "check"], capture_output=True, text=True, env=env_missing, check=False)
kinds = [json.loads(f.read_text())["type"] for f in sorted((TMP / "notify").glob("*.json"))]
check("list ABSENT + daemon running -> unlisted, not empty-list", kinds == ["daemons_unlisted"], f"kinds={kinds}")

fresh()
(TMP / "daemons.sh").write_text("# nothing\n")
env = dict(
    os.environ,
    WATCHDOG_LIST=str(TMP / "daemons.sh"),
    WATCHDOG_DAEMONS_DIR=str(TMP / "daemons"),
    WATCHDOG_NOTIFY_DIR=str(TMP / "notify"),
    WATCHDOG_STATE=str(TMP / "state.json"),
    WATCHDOG_HEARTBEAT=str(TMP / "beat"),
    WATCHDOG_DEATHS=str(TMP / "deaths.tsv"),
)
p = subprocess.run([sys.executable, WD, "check"], capture_output=True, text=True, env=env, check=False)
check(
    "empty daemon list -> says it watches nothing",
    len(sorted((TMP / "notify").glob("*.json"))) == 1 and p.returncode == 1,
    f"exit={p.returncode}",
)

fresh()
fake_daemon("alpha", '{"running": true}')
run(["alpha daemon start"])
check("healthy pass stamps the heartbeat", (TMP / "beat").exists() and (TMP / "beat").read_text().strip() != "", "no heartbeat")

# A death must land in the deaths ledger with a bounded last-seen, which is the only record a
# silent death leaves anywhere: it writes nothing to its own log and adds no start unless restarted.
fresh()
fake_daemon("delta", '{"running": true}')
run(["delta daemon start"])
(TMP / "delta.status").write_text('{"running": false}')
run(["delta daemon start"])
rows = (TMP / "deaths.tsv").read_text().strip().splitlines() if (TMP / "deaths.tsv").exists() else []
ok = len(rows) == 1 and rows[0].split("\t")[1] == "delta" and rows[0].split("\t")[2] != "unknown"
check("death is logged with a last-seen-alive time", ok, f"rows={rows}")

# A crash loop must escalate to an INTERRUPTING notification even though each restart "works",
# because a service held up by endless restarts looks healthy to everything except this ledger.
fresh()
fake_daemon("epsilon", '{"running": false}')
for _ in range(4):
    (TMP / "epsilon.status").write_text('{"running": false}')
    run(["epsilon daemon start"])
    (TMP / "epsilon.status").write_text('{"running": true}')
    run(["epsilon daemon start"])
notes = [json.loads(n.read_text()) for n in sorted((TMP / "notify").glob("*.json"))]
loops = [n for n in notes if n.get("repeated")]
check(
    "repeated deaths -> its own escalation, interrupting",
    len(loops) >= 1 and loops[0]["interrupt"] is True and loops[0]["deaths"] >= 3 and loops[0]["type"] == "daemon_died_repeatedly",
    f"notes={json.dumps(notes)[:400]}",
)

# CONTROL: two deaths is under the threshold and must stay an ordinary single-death report.
fresh()
fake_daemon("zeta", '{"running": false}')
for _ in range(2):
    (TMP / "zeta.status").write_text('{"running": false}')
    run(["zeta daemon start"])
    (TMP / "zeta.status").write_text('{"running": true}')
    run(["zeta daemon start"])
notes = [json.loads(n.read_text()) for n in sorted((TMP / "notify").glob("*.json"))]
check("control: two deaths is not an escalation", not any(n.get("repeated") for n in notes), f"notes={json.dumps(notes)[:300]}")

# THE HANG. This is the bug that actually shipped: subprocess.run(timeout=) kills only the direct
# child and then blocks reading pipes a grandchild still holds, so one hanging start froze the whole
# sweep for six minutes and the heartbeat with it. The fake start below spawns a background sleeper
# that inherits the pipe, which is exactly the shape `dashboard daemon start` had.
import time as _time

fresh()
# A hanging STATUS is the only unbounded wait left now that nothing is ever started. One sick daemon
# must not stall the sweep, or the watcher stops watching every other daemon on the box.
(TMP / "bin" / "hangs").write_text('#!/bin/sh\nif [ "$1" = "daemon" ] && [ "$2" = "status" ]; then sleep 300 & sleep 300; fi\n')
(TMP / "bin" / "hangs").chmod(0o755)
_t0 = _time.time()
code, out, notes = run(["hangs daemon start"])
_elapsed = _time.time() - _t0
check(
    "a hanging status cannot freeze the sweep",
    _elapsed < 20 and (TMP / "beat").exists(),
    f"elapsed={_elapsed:.1f}s beat={(TMP / 'beat').exists()} out={out}",
)

print()
print(f"{sum(1 for r in results if r)}/{len(results)} passed")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if all(results) else 1)
