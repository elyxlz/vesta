# CGO build environment for the telegram CLI: one owner, sourced by the launcher
# (and by any check script). Telegram uses mattn/go-sqlite3 with FTS5 for
# full-text message search, which needs CGO and the FTS5 compile flag.
export CGO_ENABLED=1
export CGO_CFLAGS="-DSQLITE_ENABLE_FTS5"
export CGO_LDFLAGS="-lm"
