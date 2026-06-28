Four skills were renamed so their names describe what they actually are, not a whole category they only cover a slice of:

- `finance` -> `enable-banking` (Enable Banking open banking, EU/EEA only, no UK)
- `tv` -> `samsung-tv` (Samsung Smart TV over WebSocket, not any TV)
- `media-server` -> `torrents` (qBittorrent + tracker search over SSH, not a Plex/Jellyfin manager)
- `icloud` -> `icloud-photos` (iCloud shared-album photos only, not Mail/Drive/Calendar)

Only the skill **identity** changed (directory + the `name:` in its `SKILL.md`). The CLI commands (`finance`, `finance-watcher`, `icloud`), the uv tools, the `screen` session names, the data directories (`~/.finance`, `~/.icloud`, `~/.tv`) and the `MEDIA_SERVER_*` env vars are all **unchanged**, so your bank private key, iCloud session, TV pairing token, running watcher and SSH config keep working with no reconfiguration.

This migration only re-points your installed-skills set at the new names. It does nothing for skills you never installed. Safe to run more than once: every step checks whether it is already in the end state and no-ops if so.

### 0. First check: do you even have any of these? (the common case)

These four skills are niche and most agents have none of them installed. Check before doing anything else:

```bash
ls -d ~/agent/skills/finance ~/agent/skills/tv ~/agent/skills/media-server ~/agent/skills/icloud 2>/dev/null
```

If that prints nothing, you have none of the renamed skills and there is **nothing to migrate**. Call `mark_migration_applied` with `name="2026-06-rename-overgeneric-skills"` now and stop. Do not run steps 1 to 4.

If it lists one or more directories, do steps 1 to 4 for only those, then mark it applied in step 5. The git, grep and sparse-checkout commands below are defensive and may print harmless errors when something is already in its end state. Such an error is never a reason to leave this migration unmarked: once you have done what you can, **always finish with step 5**.

### 1. Install the renamed skills you had installed

This installs each new name only if you currently have the old one in your sparse-checkout (i.e. you actually installed it). It leaves the old copy in place for step 2.

```bash
SPARSE="$(git -C ~ rev-parse --absolute-git-dir)/info/sparse-checkout"
install_new() {  # $1=old name, $2=new name
  grep -qFx "/agent/skills/$1/" "$SPARSE" || return 0      # never installed $1 -> skip
  [ -d ~/agent/skills/"$2" ] && return 0                   # $2 already installed -> skip
  ~/agent/skills/skills-registry/scripts/skills-install "$2" || true
}
install_new finance       enable-banking
install_new tv            samsung-tv
install_new media-server  torrents
install_new icloud        icloud-photos
```

### 2. Carry your in-file personalization forward

Auth and config live in the data directories, which did not move, so most personalization is preserved automatically. The exception is values you edited directly inside a `SKILL.md` or the skill's code. If the old skill is still on disk (this migration ran before your next upstream sync), copy those edits into the new skill:

- **samsung-tv**: if `~/agent/skills/tv/SKILL.md` has your real TV MAC/IP filled in but `~/agent/skills/samsung-tv/SKILL.md` still shows the `<TV_MAC>` / `<TV_IP>` placeholders, copy your values across. (After a normal upstream sync, git carries these over automatically and there is nothing to do.)
- **enable-banking**: if you customized the bank `aspsp` name/country in `~/agent/skills/finance/cli/src/finance_cli/enablebanking.py`, copy that change into the same file under `~/agent/skills/enable-banking/`.

If the old skill is already gone from disk, your edits were carried over by the sync's rename detection; there is nothing to do here.

### 3. Drop the old skill names from your sparse-checkout

Now remove the stale entries so the old directories disappear and only the new names remain installed:

```bash
SPARSE="$(git -C ~ rev-parse --absolute-git-dir)/info/sparse-checkout"
drop_old() {  # $1=old name, $2=new name
  grep -qFx "/agent/skills/$1/" "$SPARSE" || return 0      # already dropped -> skip
  [ -d ~/agent/skills/"$2" ] || return 0                   # new one not installed yet -> keep old until it is
  grep -vFx "/agent/skills/$1/" "$SPARSE" > "$SPARSE.tmp" && mv "$SPARSE.tmp" "$SPARSE"
  git -C ~ sparse-checkout reapply
}
drop_old finance       enable-banking
drop_old tv            samsung-tv
drop_old media-server  torrents
drop_old icloud        icloud-photos
```

If `sparse-checkout reapply` complains about local changes to an old skill directory, commit them first (`git -C ~ add agent/skills && git -C ~ commit -m "checkpoint skill personalization"`) and run the block again.

### 4. One thing to re-point manually (torrents only)

If you set up tracker search and registered the TorrentLeech plugin on your remote qBittorrent, its search-plugin `sources` path pointed at `.../agent/skills/media-server/plugins/torrentleech/torrentleech.py`. Re-register it with the new `.../agent/skills/torrents/...` path next time you use tracker search. Adding torrents by magnet/URL is unaffected.

### 5. Mark this migration applied

Call `mark_migration_applied` with `name="2026-06-rename-overgeneric-skills"`. Do this even if a step above printed an error or you are unsure a block fully applied: the migration is idempotent, so only genuinely-missing pieces would re-run on a later boot. The one outcome to avoid is leaving it unmarked because a defensive command failed.
