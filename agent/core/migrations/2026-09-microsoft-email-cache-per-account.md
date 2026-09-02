`microsoft email get` saves each fetched body under `~/.microsoft/emails/<account>/`, one directory per signed-in account (the address lowercased, every character that is not a letter or digit replaced by `_`), so `microsoft auth remove --account <email>` deletes that account's saved bodies together with its sign-in. A file sitting directly in `~/.microsoft/emails/` belongs to no account, so no command ever deletes it. Remove those files. Safe to run more than once: after step 2 the count in step 1 is 0.

### 1. Count the files that belong to no account

```bash
find ~/.microsoft/emails -maxdepth 1 -type f 2>/dev/null | wc -l
```

If the directory does not exist or the count is 0, there is nothing to do: skip to step 3.

### 2. Delete them

Each file is a cache entry: `email get` saves a fresh copy the next time that message is read, so nothing is lost. Delete files only; the subdirectories are the per-account caches and stay.

```bash
find ~/.microsoft/emails -maxdepth 1 -type f -delete
```

Re-run the count from step 1 and confirm it prints 0.

### 3. Mark this migration applied

Call `mark_migration_applied` with `name="2026-09-microsoft-email-cache-per-account"`.
