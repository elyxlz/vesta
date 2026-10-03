#!/usr/bin/env bash
# One isolated dev gateway and agent per worktree, built from this worktree.
# Isolation: HOME (config, keys, repos) and USER (containers, networks, images) are per branch.
# This script always starts the dev gateway standalone (never through systemd); it waits for
# the gateway's own health check before running `vestad provision`, which is what lets
# provision reuse that already-answering gateway instead of falling back to a systemd bootstrap.
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage: scripts/dev-instance.sh up --provider <provider.json> [--agent <name>]
       scripts/dev-instance.sh status | logs | down
`up` creates a new instance; run `down` first to rebuild an existing one.
<provider.json> holds the dev agent's own provider object, for example
{"kind":"claude","credentials":"<its own .credentials.json>"}; never copy a live agent's file.
EOF
  exit 2
}

repo_root=$(git rev-parse --show-toplevel)
branch=$(git -C "$repo_root" rev-parse --abbrev-ref HEAD)
# A short, human-readable prefix plus a hash of the worktree path: the prefix alone collides
# (feat/foo vs feat-foo both slugify to the same string, and every detached HEAD is "head"),
# and the path hash makes each worktree unique while keeping the whole slug well under the
# Docker/Linux-friendly length ceiling.
slug_prefix=$(printf '%s' "$branch" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-' | sed 's/-\+/-/g; s/^-//; s/-$//' | cut -c1-16)
slug_hash=$(printf '%s' "$repo_root" | sha1sum | cut -c1-8)
slug="${slug_prefix}-${slug_hash}"
dev_user="dev-${slug}"
dev_home="${HOME}/.vesta-dev/${slug}"
config_dir="${dev_home}/.config/vesta/vestad"
image="vesta:dev-${slug}"
pid_file="${dev_home}/vestad.pid"
vestad_bin="${repo_root}/vestad/target/debug/vestad"
health_wait_secs=60
stop_wait_secs=15

dev_env() {
  env HOME="$dev_home" USER="$dev_user" VESTAD_AGENT_IMAGE="$image" "$@"
}

running() {
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

# Poll the dev gateway's own health endpoint (https port + 1) until it answers or
# health_wait_secs elapses. `vestad provision` only reuses an already-answering gateway
# within its own short internal probe, so a still-booting gateway here would make it
# fall through to a systemd bootstrap instead, which this script must never trigger.
wait_for_gateway() {
  local waited=0
  local port health_url
  while (( waited < health_wait_secs )); do
    if ! running; then
      echo "the dev gateway process exited before it became ready: see ${dev_home}/serve.out" >&2
      return 1
    fi
    if [[ -f "${config_dir}/port" ]]; then
      port=$(cat "${config_dir}/port")
      health_url="http://127.0.0.1:$((port + 1))/health"
      if curl -fsS -o /dev/null "$health_url" 2>/dev/null; then
        return 0
      fi
    fi
    sleep 1
    waited=$((waited + 1))
  done
  echo "the dev gateway did not answer within ${health_wait_secs}s: see ${dev_home}/serve.out" >&2
  return 1
}

cmd_up() {
  local provider_file="" agent="dev"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --provider) provider_file="$2"; shift 2 ;;
      --agent) agent="$2"; shift 2 ;;
      *) usage ;;
    esac
  done
  [[ -n "$provider_file" && -f "$provider_file" ]] || usage
  [[ "$agent" =~ ^[a-z0-9-]+$ ]] || { echo "--agent must match [a-z0-9-]+" >&2; exit 2; }
  if running; then
    echo "the dev instance for ${branch} already runs: run \`$0 down\` first to rebuild it" >&2
    exit 1
  fi
  mkdir -p "$dev_home"
  echo "building vestad and the agent image for ${branch}..." >&2
  (cd "$repo_root/vestad" && PATH="$HOME/.cargo/bin:$PATH" cargo build -p vestad)
  docker build -q -t "$image" -f "$repo_root/vestad/Dockerfile" "$repo_root" >&2
  # Invoke `env` directly rather than through the `dev_env` function: a backgrounded call to
  # a shell function runs in its own subshell, so `$!` would capture that subshell, not
  # vestad, and killing it later would leave vestad orphaned. `env` execs `nohup`, which
  # execs vestad, so this way `$!` is vestad's own pid.
  env HOME="$dev_home" USER="$dev_user" VESTAD_AGENT_IMAGE="$image" \
    nohup "$vestad_bin" serve --standalone --no-tunnel >"${dev_home}/serve.out" 2>&1 &
  echo $! >"$pid_file"
  wait_for_gateway
  # The config holds the provider credentials: remove it once provision has read it.
  local config="${dev_home}/provision.json" status=0
  (umask 077 && printf '{"agent_name":"%s","provider":%s}' "$agent" "$(cat "$provider_file")" >"$config")
  dev_env "$vestad_bin" provision "$config" || status=$?
  rm -f "$config"
  return "$status"
}

cmd_status() {
  running && echo "gateway: running (pid $(cat "$pid_file"))" || echo "gateway: stopped"
  if [[ -f "${config_dir}/port" ]]; then
    local port; port=$(cat "${config_dir}/port")
    echo "app: http://localhost:$((port + 1))/app#k=$(cat "${config_dir}/api-key")"
  fi
  docker ps -a --filter "label=vesta.user=${dev_user}" --format '{{.Names}}\t{{.Status}}'
}

cmd_logs() {
  tail -n 200 -F "${config_dir}"/vestad.log.* &
  local tail_pid=$!
  trap 'kill $tail_pid 2>/dev/null' EXIT
  for container in $(docker ps --filter "label=vesta.user=${dev_user}" --format '{{.Names}}'); do
    docker logs -f --tail 100 "$container" &
  done
  wait
}

cmd_down() {
  if running; then
    local pid waited=0
    pid=$(cat "$pid_file")
    kill "$pid"
    while kill -0 "$pid" 2>/dev/null && (( waited < stop_wait_secs )); do
      sleep 1
      waited=$((waited + 1))
    done
  fi
  local containers networks
  containers=$(docker ps -aq --filter "label=vesta.user=${dev_user}")
  networks=""
  if [[ -n "$containers" ]]; then
    # Networks carry no label of their own, so collect this instance's network names from its
    # own labeled containers before removing them; a name substring filter on the network list
    # would also match another branch whose slug happens to be a prefix of this one.
    networks=$(printf '%s\n' "$containers" \
      | xargs docker inspect -f '{{range $net, $cfg := .NetworkSettings.Networks}}{{$net}}{{"\n"}}{{end}}' \
      | sort -u || true)
    printf '%s\n' "$containers" | xargs -r docker rm -f >/dev/null
  fi
  while IFS= read -r net; do
    case "$net" in
      vesta-agent-*) docker network rm "$net" >/dev/null 2>&1 || true ;;
    esac
  done <<<"$networks"
  # Untag by reference, never by id: an id can be shared with another worktree's identical
  # build or with `vesta:local`, and `rmi -f` on a shared id would untag those too.
  docker rmi "$image" >/dev/null 2>&1 || true
  docker images --filter "reference=vesta-rebuild-${dev_user}" --format '{{.Repository}}:{{.Tag}}' \
    | xargs -r docker rmi >/dev/null 2>&1 || true
  rm -rf "$dev_home"
  echo "dev instance for ${branch} removed" >&2
}

case "${1:-}" in
  up) shift; cmd_up "$@" ;;
  status) cmd_status ;;
  logs) cmd_logs ;;
  down) cmd_down ;;
  *) usage ;;
esac
