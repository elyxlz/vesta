#!/usr/bin/env bash
# Reality check: probe the SYSTEM, not the record of the system.
#
# The retrospective re-reads previous summaries, so it can only re-certify what someone already
# noticed, and is blind to silent failure. Proof: a calendar credential died and the daemon logged
# the same error 3,903 times over fourteen days while `status` said running:true. Seven dreams
# missed it; daytime work found it. A ledger audited against another ledger is not a measurement.
# Run FIRST. Every RED is fixed tonight or explicitly written off; it does not get to evaporate.

RED=0
red()  { printf '  RED   %s\n' "$1"; RED=$((RED+1)); }
ok()   { printf '  ok    %s\n' "$1"; }
warn() { printf '  warn  %s\n' "$1"; }

now=$(date -u +%s)

# This container's own CIDR, computed rather than hardcoded: it is what a whitelist needs to contain,
# and it differs per box. Falls back to the bare IP if the route table cannot be parsed.
_subnet() {
  python3 - <<'EOS' 2>/dev/null || hostname -i 2>/dev/null | awk '{print $1}'
import struct, socket
for line in open("/proc/net/route").read().splitlines()[1:]:
    f = line.split()
    if len(f) > 7 and f[1] != "00000000":
        dest = socket.inet_ntoa(struct.pack("<I", int(f[1], 16)))
        mask = int(f[7], 16)
        bits = bin(mask).count("1")
        print(f"{dest}/{bits}")
        break
EOS
}


echo "== daemons: alive AND doing their job =="
# Derive the daemon list from the restart skill rather than hardcoding it, so this fits any
# instance and cannot drift as skills are added or removed. Same trick the proactive-check preflight
# uses. A hardcoded list silently stops covering whatever was installed after it was written.
DAEMONS=$(sed -n 's/^\([a-z0-9-]*\) daemon start.*/\1/p' ~/agent/skills/restart/SKILL.md 2>/dev/null | sort -u)
[ -z "$DAEMONS" ] && red "could not read any daemon from the restart skill (list empty = this whole section is vacuous)"
for d in $DAEMONS; do
  s=$("$d" daemon status 2>/dev/null)
  running=$(printf '%s' "$s" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("running"))
except Exception: print("?")' 2>/dev/null)
  [ "$running" = "True" ] && ok "$d running" || red "$d NOT running (status=$running)"
done

echo
echo "== integrations: is the credential still good? =="
# Liveness is not health. Each of these has a third-party credential that can die silently.

# apple-calendar: how stale is the snapshot actually being served?
ls=$(apple-calendar events --days 1 2>/dev/null | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("last_sync") or "")
except Exception: print("")' 2>/dev/null)
if [ -n "$ls" ]; then
  lse=$(date -u -d "$ls" +%s 2>/dev/null || echo 0)
  age=$(( (now - lse) / 3600 ))
  if [ "$age" -gt 6 ]; then red "apple-calendar snapshot is ${age}h old (serving stale data as current)"
  else ok "apple-calendar synced ${age}h ago"; fi
else
  red "apple-calendar: could not read last_sync at all"
fi
# and its own failure record, if the sync-health fix is in place
if [ -f ~/.apple-calendar/sync-health.json ]; then
  cf=$(python3 -c 'import json;print(json.load(open("/root/.apple-calendar/sync-health.json")).get("consecutive_failures",0))' 2>/dev/null)
  [ "${cf:-0}" -gt 0 ] && red "apple-calendar has $cf consecutive sync failures" || ok "apple-calendar sync-health clean"
fi

# whatsapp: the only channel that reaches the user first
wa=$(whatsapp daemon status 2>/dev/null | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin); c=d.get("connection",{})
    print(f'"'"'{c.get("auth_status")}|{c.get("connected")}'"'"')
except Exception: print("?|?")' 2>/dev/null)
case "$wa" in
  authenticated\|True) ok "whatsapp authenticated + connected" ;;
  *) red "whatsapp degraded ($wa) - the user cannot reach me" ;;
esac

# email-client: a poll daemon that is up but erroring looks identical to one that is working.
# A MISSING probe is itself RED. A check that silently skips is how the original bug survived.
ecl=""
for cand in ~/agent/logs/email-client.log ~/.email-client/poll_daemon.log; do
  [ -f "$cand" ] && { ecl="$cand"; break; }
done
if [ -z "$ecl" ]; then
  red "email-client: no log found to probe (check silently skipped = the original bug)"
else
  lm=$(stat -c %Y "$ecl" 2>/dev/null || echo 0)
  age=$(( (now - lm) / 60 ))
  [ "$age" -gt 120 ] && red "email-client log silent for ${age}min ($ecl)" || ok "email-client log fresh (${age}min)"
  tail -60 "$ecl" 2>/dev/null | grep -qiE 'login failed|invalid credentials|authenticationfailed' \
    && red "email-client log shows auth failures" || ok "email-client no auth failures in tail"
fi

echo
echo
echo "== media stack: the integrations with NO daemon of their own =="
# ADDED 2026-08-03 after qBittorrent access died silently for EIGHT DAYS. It last worked Jul 26; on
# Aug 2 Emi asked for a download and only then did it turn out the API had been answering 403 the
# whole time. Nothing here owns a daemon, so nothing in the loop above would ever notice: this is the
# apple-calendar signature exactly (a working-looking system whose every operation fails), and it was
# found by a user request rather than by a probe, which is the charge the whole script exists to answer.
if [ -z "$BOX_HOST" ]; then
  red "BOX_HOST unset, media probes SKIPPED (a check that skips in silence is the original bug)"
else
  # qBittorrent: 403 is its not-authenticated reply and is exactly how the Aug 2 outage presented.
  qb=$(curl -s -o /dev/null -m 8 -w '%{http_code}' "http://$BOX_HOST:8888/api/v2/torrents/info" 2>/dev/null)
  case "$qb" in
    200) ok "qBittorrent API authorized ($qb)" ;;
    403) red "qBittorrent API returns 403 NOT AUTHORIZED: downloads cannot be added. Whitelist this container's subnet ($(_subnet)) under qB Options > Web UI > bypass auth for whitelisted subnets" ;;
    000) red "qBittorrent unreachable at $BOX_HOST:8888 (is the box up?)" ;;
    *)   red "qBittorrent API unexpected status $qb" ;;
  esac

  # Plex: a live token must 200 AND a deliberately bad one must NOT, else the check proves nothing.
  ptok=$(python3 -c 'import json;print(json.load(open("/root/.plex/config.json")).get("token",""))' 2>/dev/null)
  if [ -z "$ptok" ]; then
    red "no Plex token on disk (~/.plex/config.json), Plex probe SKIPPED"
  else
    pgood=$(curl -s -o /dev/null -m 8 -w '%{http_code}' "http://$BOX_HOST:32400/library/sections?X-Plex-Token=$ptok" 2>/dev/null)
    pbad=$(curl -s -o /dev/null -m 8 -w '%{http_code}' "http://$BOX_HOST:32400/library/sections?X-Plex-Token=definitely-not-a-token-$$" 2>/dev/null)
    if [ "$pgood" = "200" ] && [ "$pbad" != "200" ]; then
      ok "Plex token valid (good=$pgood, known-bad control=$pbad)"
    elif [ "$pgood" = "200" ]; then
      red "Plex answers 200 to a GARBAGE token too (control=$pbad): this probe proves nothing, treat as unverified"
    else
      red "Plex token rejected or server unreachable (good=$pgood, control=$pbad)"
    fi
  fi

  # VPN: only ever needed for tracker search, i.e. the same moment qB is needed. Same risk profile as
  # qB above and that is the point: what rots unseen is not the most important dependency, it is the
  # one with the LONGEST GAP BETWEEN USES. Anything touched nightly (the GitHub App token, email)
  # fails loudly on its own; anything touched weekly can be dead for a week before a user finds it.
  vp=$(~/agent/skills/vpn/vpn proxy-url 2>/dev/null | sed 's#socks5://#socks5h://#')
  if [ -z "$vp" ]; then
    red "VPN proxy-url is empty: tracker search (apibay) will fail when next needed"
  else
    vc=$(curl -s -o /dev/null -m 12 --proxy "$vp" -w '%{http_code}' "https://apibay.org/q.php?q=test&cat=200" 2>/dev/null)
    [ "$vc" = "200" ] && ok "VPN proxy works for tracker search ($vc)" \
      || red "VPN proxy set but tracker search fails ($vc): media requests will dead-end"
  fi
fi

echo
echo "== silent-failure sweep: daemons running while every operation fails =="
# The apple-calendar signature: same error, over and over, for days, with nobody reading the log.
# A glob that matches nothing used to print nothing and add no RED, which made a moved or renamed
# log dir look GREENER than the night before. That is the same silent-skip this script exists to kill.
scanned=0
for f in ~/agent/logs/*.log; do
  [ -f "$f" ] || continue
  scanned=$((scanned+1))
  n=$(tail -400 "$f" 2>/dev/null | grep -icE 'unauthorized|invalid.credential|401|403|auth.*fail' || true)
  [ "${n:-0}" -ge 20 ] && red "$(basename "$f"): ${n} auth-ish errors in last 400 lines"
done
[ "$scanned" -eq 0 ] && red "no logs found in ~/agent/logs (sweep scanned NOTHING = the original bug)" \
  || ok "swept $scanned log file(s)"

echo
echo "== reachability: is anything bound loopback-only? =="
# Do NOT probe the public gateway and treat 401 as "routing works": vestad answers 401 BEFORE
# contacting any upstream, so a service that does not exist returns exactly what a healthy private
# one does. That version printed ten meaningless green lines and would have passed the very bug it
# was written for. This tests the failure directly and needs no credential: a process bound to
# 127.0.0.1 answers on loopback and REFUSES on the container's own network address, which is where
# the host-side proxy reaches it. lo=answer + net=refused IS the signature, for every service.
IP=$(hostname -i 2>/dev/null | awk '{print $1}')
if [ -z "$IP" ] || [ "$IP" = "127.0.0.1" ]; then
  red "could not determine the container IP, bind probe SKIPPED (a check that skips in silence is the original bug)"
else
  svcs=$(curl -sk -m 10 "https://$BOX_HOST:$VESTAD_PORT/agents/$AGENT_NAME/services" \
           -H "X-Agent-Token: $AGENT_TOKEN" 2>/dev/null \
         | python3 -c '
import json,sys
try:
    d = json.load(sys.stdin)["services"]
    for k, v in d.items():
        if not k.startswith("_port_holder"):
            print(k, v["port"])
except Exception:
    pass' 2>/dev/null)
  if [ -z "$svcs" ]; then
    red "could not list registered services, bind probe SKIPPED (= the original bug)"
  else
    printf '%s\n' "$svcs" | while read -r name port; do
      [ -n "$port" ] || continue
      lo=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:$port/health" 2>/dev/null)
      net=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "http://$IP:$port/health" 2>/dev/null)
      if [ "$lo" != "000" ] && [ "$net" = "000" ]; then
        red "$name is BOUND LOOPBACK-ONLY (lo=$lo net=refused): healthy to me, unreachable for her. Fix the bind to 0.0.0.0"
      elif [ "$lo" = "000" ] && [ "$net" = "000" ]; then
        warn "$name not listening on :$port (on-demand or portless, check if it should be up)"
      else
        ok "$name bound correctly (lo=$lo net=$net)"
      fi
    done
  fi
fi

echo
echo "== public services, end to end through the gateway (with a known-bad control) =="
# Only PUBLIC services can be validated this way, because vestad 401s a private one before it ever
# reaches the upstream. A control request to a service that does not exist pins what "broken" looks
# like, so a green line here cannot be the gateway answering on the service's behalf.
if [ -n "$VESTAD_TUNNEL" ] && [ -n "$AGENT_NAME" ]; then
  B="$VESTAD_TUNNEL/agents/$AGENT_NAME"
  control=$(curl -s -o /dev/null -m 8 -w '%{http_code}' "$B/nosuchsvc-control-$$/health" 2>/dev/null)
  pub=$(curl -sk -m 10 "https://$BOX_HOST:$VESTAD_PORT/agents/$AGENT_NAME/services" \
          -H "X-Agent-Token: $AGENT_TOKEN" 2>/dev/null \
        | python3 -c 'import json,sys
try: print("\n".join(k for k,v in json.load(sys.stdin)["services"].items() if v.get("public") and k!="browser"))
except Exception: pass' 2>/dev/null)
  if [ -z "$pub" ]; then
    warn "no public services registered to probe"
  else
    for s in $pub; do
      c=$(curl -s -o /dev/null -m 8 -w '%{http_code}' "$B/$s/health" 2>/dev/null)
      if [ "$c" = "$control" ]; then
        red "$s returns the same code as a NONEXISTENT service ($c): this line proves nothing, treat as broken"
      elif [ "$c" = "502" ] || [ "$c" = "000" ]; then
        red "$s unreachable through the gateway ($c)"
      else
        ok "$s reachable through the gateway ($c, control=$control)"
      fi
    done
  fi
else
  red "VESTAD_TUNNEL/AGENT_NAME unset, gateway probe SKIPPED (= the original bug)"
fi

echo "== reminders: is the scheduler still holding anything? =="
# Generic floor: an empty reminder store means every timed commitment silently evaporated, which is
# the same class of failure as a daemon that is up but does nothing. Instances that have ONE nudge
# that must always exist (a nightly medication reminder, a recurring handover) should add a specific
# grep for it here; that check is per-instance, this one is the universal floor.
_rem=$(tasks remind list 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | grep -cE '^in |^once|^every' || true)
if [ "${_rem:-0}" -gt 0 ]; then ok "$_rem reminder(s) armed"
else red "NO reminders armed at all: every timed commitment has evaporated"; fi

echo
echo "== disk =="
use=$(df -h / | awk 'NR==2{print $5}' | tr -d '%')
[ "$use" -ge 92 ] && red "disk ${use}%" || ok "disk ${use}%"

echo
if [ "$RED" -gt 0 ]; then
  echo "RESULT: $RED RED. Fix tonight, or write down explicitly why not. Do not carry silently."
  exit 1
fi
echo "RESULT: all clear (measured, not remembered)."
