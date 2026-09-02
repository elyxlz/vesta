#!/bin/sh
set -eu

# node_modules/ and dist/ are untracked build artifacts, so each is compared with its inputs: one
# that is present but older than the source it was built from is remade, and a current one is left
# alone, which is what lets this run before every launch. `find -newer` is strictly newer; npm
# writes node_modules/.package-lock.json last on every install and a build writes dist/index.html,
# so a finished step reads as current on its own. Directories count as inputs too: deleting a
# source file leaves no newer file behind, only a newer src/.
cd "$(dirname "$0")/../app"

[ -f node_modules/.package-lock.json ] && [ -z "$(find package-lock.json -newer node_modules/.package-lock.json)" ] || npm install
[ -f dist/index.html ] && [ -z "$(find src index.html vite.config.ts package-lock.json tsconfig*.json -newer dist/index.html -print -quit)" ] || npx vite build
