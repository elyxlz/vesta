#!/usr/bin/env bash
# One isolated dev gateway and agent per worktree, built from this worktree.
# Isolation: HOME (config, keys, repos) and USER (containers, networks, images) are per branch,
# and a dev gateway never touches systemd, so the machine's real gateways stay untouched.
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage: scripts/dev-instance.sh up --provider <provider.json> [--agent <name>]
       scripts/dev-instance.sh status | logs | down
<provider.json> holds the dev agent's own provider object, for example
{"kind":"claude","credentials":"<its own .credentials.json>"}; never copy a live agent's file.
EOF
  exit 2
}

repo_root=$(git rev-parse --show-toplevel)
branch=$(git -C "$repo_root" rev-parse --abbrev-ref HEAD)
slug=$(printf '%s' "$branch" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-' | sed 's/-\+/-/g; s/^-//; s/-$//' | cut -c1-24)
dev_user="dev-${slug}"
dev_home="${HOME}/.vesta-dev/${slug}"
config_dir="${dev_home}/.config/vesta/vestad"
image="vesta:dev-${slug}"
pid_file="${dev_home}/vestad.pid"
vestad_bin="${repo_root}/target/debug/vestad"
health_wait_secs=60

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
  mkdir -p "$dev_home"
  echo "building vestad and the agent image for ${branch}..." >&2
  (cd "$repo_root/vestad" && PATH="$HOME/.cargo/bin:$PATH" cargo build -p vestad)
  docker build -q -t "$image" -f "$repo_root/vestad/Dockerfile" "$repo_root" >&2
  if ! running; then
    dev_env nohup "$vestad_bin" serve --standalone --no-tunnel >"${dev_home}/serve.out" 2>&1 &
    echo $! >"$pid_file"
  fi
  wait_for_gateway
  local config="${dev_home}/provision.json"
  (umask 077 && printf '{"agent_name":"%s","provider":%s}' "$agent" "$(cat "$provider_file")" >"$config")
  dev_env "$vestad_bin" provision "$config"
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
  if running; then kill "$(cat "$pid_file")"; fi
  docker ps -aq --filter "label=vesta.user=${dev_user}" | xargs -r docker rm -f >/dev/null
  docker network ls -q --filter "name=vesta-agent-${dev_user}-" | xargs -r docker network rm >/dev/null
  { docker images -q --filter "reference=vesta-rebuild-${dev_user}"; docker images -q "$image"; } | xargs -r docker rmi -f >/dev/null
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
