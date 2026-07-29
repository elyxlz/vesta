---
name: ssh-tunnel
description: Expose this machine over SSH via bore (public TCP tunnel).
---

# SSH Access (CLI: ssh-tunnel)

Exposes this machine over the internet via [bore](https://github.com/ekzhang/bore), a free TCP relay. Runs its own sshd on a dynamically allocated port inside the container (independent of the host SSH server, no port conflicts between containers) so all auth is fully controlled. No account required. The connecting machine only needs a standard SSH client.

The command is `ssh-tunnel`. `ssh` itself is the system SSH client, so the skill takes the longer name rather than shadowing it.

## Get the client's public key first

Ask the user to run this on the machine that will be connecting:

```bash
cat ~/.ssh/id_ed25519.pub
# or if using RSA:
cat ~/.ssh/id_rsa.pub
```

If they don't have a key yet:
```bash
ssh-keygen -t ed25519   # press Enter for all prompts
cat ~/.ssh/id_ed25519.pub
```

They should paste the full output (one line starting with `ssh-ed25519` or `ssh-rsa`).

## Authorize the key and bring up sshd

```bash
ssh-tunnel setup "ssh-ed25519 AAAA... user@laptop"
```

Authorizes the key and starts the sshd the tunnel points at, printing `{"status":"ready","sshd_port":<port>}`. Idempotent: a second key is added alongside the first, and an sshd already running keeps its port, so authorizing another machine never disturbs a live tunnel.

A container restart takes sshd with it but leaves `~/.ssh/authorized_keys` alone, so once any key is authorized `ssh-tunnel setup` with no argument brings sshd back up on a fresh port. The key argument is only required the first time, and passing one still authorizes it.

## Start the tunnel

```bash
ssh-tunnel daemon start
```

`start`, `stop`, `restart`, and `status` each print one line of JSON. `status` also carries `"sshd"`, since the sshd is the other half of reachability and the daemon verbs never touch it: `{"running":false,"port":null,"sshd":true}` is a machine with sshd up and no tunnel to it, and `"sshd":false` is the state `ssh-tunnel setup` fixes. Log: `~/agent/logs/ssh-tunnel.log`.

## Connect from the other machine

bore picks the public port and writes it to the log:

```bash
grep -o 'bore\.pub:[0-9]*' ~/agent/logs/ssh-tunnel.log | tail -1
```

Give the user that port:

```bash
ssh -o StrictHostKeyChecking=accept-new root@bore.pub -p 12345
```

The host key is the container's sshd key and stays stable across bore reconnects.

If the connecting machine has multiple SSH keys and the wrong one is picked:
```bash
ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=accept-new root@bore.pub -p 12345
```

## Stop

```bash
ssh-tunnel daemon stop
```

Ends the tunnel, which is what makes the machine unreachable from outside. The sshd stays up (`ssh-tunnel daemon status` shows it as `"sshd":true`) and the authorized keys stay in `~/.ssh/authorized_keys`, so the next `daemon start` needs no setup.

## Notes

- Auth is key-only. Password auth and root password login are disabled.
- bore picks a new public port every time the tunnel starts, so share the current one after each start.
- bore.pub is a public free service. Don't use it for long-term persistent access; it's for temporary sessions.
- To copy files over the tunnel: `scp -P 12345 -o StrictHostKeyChecking=accept-new file root@bore.pub:~/destination/`
- To use rsync: `rsync -e "ssh -p 12345 -o StrictHostKeyChecking=accept-new" file root@bore.pub:~/destination/`
