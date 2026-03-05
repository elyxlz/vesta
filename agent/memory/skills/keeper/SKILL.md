---
name: keeper
description: This skill should be used when the user asks about "passwords", "credentials", "vault", "secrets", "keeper", "password manager", "logins", "TOTP", "2FA codes", or needs to store, retrieve, search, share, or manage passwords and secure records.
---

# Keeper — CLI: keeper

All commands are run as one-shot calls from bash (not inside the interactive shell):
```bash
keeper "command here"
```

**Setup**: See [SETUP.md](SETUP.md)

## Records

### List and Search
```bash
keeper "l"                               # list all records
keeper "l twitter"                       # filter by keyword
keeper "search dropbox login"            # search by partial words
keeper "search aws --format json"        # JSON output
```

### View a Record
```bash
keeper "get <UID>"                       # display record details
keeper "get <UID> --unmask"              # show passwords in plain text
keeper "get <UID> --format json"         # JSON output
keeper "get <UID> --format password"     # show only the password
```

### Get a Password
```bash
keeper "find-password <UID>"
keeper "clipboard-copy <UID>"            # copy password to clipboard
keeper "clipboard-copy <UID> -l"         # copy username
keeper "clipboard-copy <UID> -t"         # copy TOTP code
keeper "clipboard-copy <UID> --field url"
```

### Create a Record
```bash
keeper "record-add --title 'Gmail' --record-type login login=user@gmail.com password='\$GEN:rand,20' url=https://accounts.google.com"

keeper "record-add -t 'Server' -rt serverCredentials host='\$JSON:{\"hostName\":\"10.0.1.50\",\"port\":\"22\"}' login=admin password='\$GEN:rand,24'"
```

Record types: `login`, `bankAccount`, `bankCard`, `serverCredentials`, `sshKeys`, `databaseCredentials`, `encryptedNotes`, `softwareLicense`, `membership`, `contact`, `address`, `wifiCredentials`

Password generation: `$GEN:rand,<length>` (random), `$GEN:dice,<words>` (diceware)

### Update a Record
```bash
keeper "record-update -r <UID> --title 'New Title'"
keeper "record-update -r <UID> login=new_user password='\$GEN:rand,20'"
keeper "record-update -r <UID> --notes 'Updated notes'"
```

### Delete a Record
```bash
keeper "rm <UID> -f"                     # -f skips confirmation
keeper "trash list"                      # list deleted records
keeper "trash restore <UID>"             # restore from trash
```

## Folders

```bash
keeper "ls"                              # list current folder
keeper "ls -l"                           # detailed listing
keeper "tree"                            # full folder tree
keeper "mkdir finance/personal"          # create folder
keeper "mkdir 'Team Secrets' -sf"        # create shared folder
keeper "mv <UID> social"                 # move record to folder
```

## TOTP / 2FA Codes

```bash
keeper "totp"                            # show all TOTP codes
keeper "totp <UID>"                      # TOTP for specific record
```

## Sharing

```bash
keeper "share-record <UID> -e user@example.com"
keeper "share-record <UID> -e user@example.com --action grant -w -s"
keeper "share-record <UID> -e user@example.com --action revoke"
keeper "one-time-share create <UID> -e 1h"
```

## Password Generation

```bash
keeper "generate"                        # default
keeper "generate -c 20"                  # 20 characters
keeper "generate -c 16 -u 3 -d 3 -s 3"  # 16 chars, 3 upper, 3 digits, 3 special
keeper "generate -dr 6"                  # diceware passphrase (6 words)
```

## Notes
- All record commands accept UIDs or folder-path/record-name
- Use `--format json` on most commands for machine-readable output
- Always use `-f` on destructive commands (rm, delete) to skip interactive confirmation

## Learned Patterns

### Frequently Used Records
[Records the user accesses often]

### Vault Organization
[How the user organizes folders and records]
