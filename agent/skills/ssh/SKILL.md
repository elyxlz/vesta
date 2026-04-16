---
name: ssh
description: Use when the user wants to allow another computer to SSH into this machine, share remote access, or set up a public SSH tunnel. Creates an internet-accessible SSH endpoint via bore.
---

# SSH Access

Exposes this machine over the internet via [bore](https://github.com/ekzhang/bore), a free TCP relay. Runs its own sshd on port 2222 inside the container (independent of the host SSH server) so all auth is fully controlled. No account required. The connecting machine only needs a standard SSH client.

## Before running start.sh — get the client's public key

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

## Start the tunnel

```bash
~/vesta/skills/ssh/scripts/start.sh "ssh-ed25519 AAAA... user@laptop"
```

This will:
1. Install `openssh-server` if not already present
2. Generate SSH host keys if missing
3. Start sshd on port 2222 with key-only auth (no passwords)
4. Add the provided public key to `/root/.ssh/authorized_keys`
5. Download `bore` if not already installed
6. Open a public bore.pub tunnel and print the connection command

Running `start.sh` again with a different key adds it without removing existing ones (idempotent).

## Connect from the other machine

The script prints the exact command. It will look like:

```bash
ssh -o StrictHostKeyChecking=accept-new root@bore.pub -p 12345
```

`StrictHostKeyChecking=accept-new` accepts the host key on first connect and warns if it changes later — safer than `no`. The host key is the container's sshd key and stays stable across bore reconnects.

If the connecting machine has multiple SSH keys and the wrong one is picked:
```bash
ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=accept-new root@bore.pub -p 12345
```

## Check status

```bash
~/vesta/skills/ssh/scripts/status.sh
```

Shows whether sshd and bore are running, the current connection command, and which keys are authorized.

## Stop

```bash
~/vesta/skills/ssh/scripts/stop.sh
```

Stops both the bore tunnel and the sshd process. Authorized keys remain in `/root/.ssh/authorized_keys` for the next session.

## Notes

- Auth is key-only. Password auth and root password login are disabled.
- The bore port changes each time `start.sh` is run — share the new port with the connecting machine.
- Tunnel runs in a `screen` session named `bore-ssh`. If bore dies unexpectedly: `screen -r bore-ssh` to inspect, then re-run `start.sh`.
- bore.pub is a public free service operated by the bore project. Don't use it for long-term persistent access — it's for temporary sessions.
- To copy files over the tunnel: `scp -P 12345 -o StrictHostKeyChecking=accept-new file root@bore.pub:~/destination/`
- To use rsync: `rsync -e "ssh -p 12345 -o StrictHostKeyChecking=accept-new" file root@bore.pub:~/destination/`
