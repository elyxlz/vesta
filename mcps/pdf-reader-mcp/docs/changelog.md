# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Nothing yet.

## [0.3.9] - 2025-04-05

### Fixed

- Removed artifact download/extract steps from `publish-docker` job in workflow, as Docker build needs the full source context provided by checkout.

## [0.3.8] - 2025-04-05

### Fixed

- Removed duplicate `context: .` entry in `docker/build-push-action` step in `.github/workflows/publish.yml`.

## [0.3.7] - 2025-04-05

### Fixed

- Removed explicit `COPY tsconfig.json ./` from Dockerfile (rely on `COPY . .`).
- Explicitly set `context: .` in docker build-push action.

## [0.3.6] - 2025-04-05

### Fixed

- Explicitly added `COPY tsconfig.json ./` before `COPY . .` in Dockerfile to ensure it exists before build step.

## [0.3.5] - 2025-04-05

### Fixed

- Added `RUN ls -la` before build step in Dockerfile to debug `tsconfig.json` not found error.

## [0.3.4] - 2025-04-05

### Fixed

- Explicitly specify `tsconfig.json` path in Dockerfile build step (`RUN ./node_modules/.bin/tsc -p tsconfig.json`) to debug build failure.

## [0.3.3] - 2025-04-05

### Fixed

- Changed Dockerfile build step from `RUN npm run build` to `RUN ./node_modules/.bin/tsc` to debug build failure.

## [0.3.2] - 2025-04-05

### Fixed

- Simplified `build` script in `package.json` to only run `tsc` (removed `chmod`) to debug Docker build failure.

## [0.3.1] - 2025-04-05

### Fixed

- Attempted various fixes for GitHub Actions workflow artifact upload issue (`Error: Provided artifact name input during validation is empty`). Final attempt uses fixed artifact filename in upload/download steps.

## [0.3.0] - 2025-04-05

### Added

- `CHANGELOG.md` file based on Keep a Changelog format.
- `LICENSE` file (MIT License).
- Improved GitHub Actions workflow (`.github/workflows/publish.yml`):
  - Triggers on push to `main` branch and version tags (`v*.*.*`).
  - Conditionally archives build artifacts only on tag pushes.
  - Conditionally runs `publish-npm` and `publish-docker` jobs only on tag pushes.
  - Added `create-release` job to automatically create GitHub Releases from tags, using `CHANGELOG.md` for the body.
- Added version headers to Memory Bank files (`activeContext.md`, `progress.md`).

### Changed

- Bumped version from 0.2.2 to 0.3.0.
