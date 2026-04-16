#!/usr/bin/env bash
set -euo pipefail

main() {
  REPO="elyxlz/vesta"
  INSTALL_VERSION=""
  INSTALL_CLI=""
  INSTALL_SERVER=""
  INSTALL_APP=""

  for arg in "$@"; do
    case "$arg" in
      --version=*) INSTALL_VERSION="${arg#--version=}" ;;
      --cli) INSTALL_CLI=1 ;;
      --server) INSTALL_SERVER=1 ;;
      --app) INSTALL_APP=1 ;;
      --help|-h)
        echo "Usage: curl -fsSL https://raw.githubusercontent.com/elyxlz/vesta/master/install.sh | bash"
        echo ""
        echo "Installs vesta CLI, desktop app (if GUI available), and vestad (Linux only)."
        echo "By default, all available components for your platform are installed."
        echo ""
        echo "Options:"
        echo "  --cli              Install only the CLI"
        echo "  --server           Install only vestad (Linux only)"
        echo "  --app              Install only the desktop app"
        echo "  --version=X.Y.Z   Install a specific version"
        echo "  --help             Show this help"
        exit 0
        ;;
    esac
  done

  OS=$(uname -s | tr '[:upper:]' '[:lower:]')

  EXPLICIT_FLAGS=""
  [ -n "$INSTALL_CLI" ] || [ -n "$INSTALL_SERVER" ] || [ -n "$INSTALL_APP" ] && EXPLICIT_FLAGS=1

  # If no component flags given, install everything available for this platform
  if [ -z "$EXPLICIT_FLAGS" ]; then
    INSTALL_CLI=1
    [ "$OS" = "linux" ] && INSTALL_SERVER=1
    INSTALL_APP=1
  fi
  ARCH=$(uname -m)

  case "$ARCH" in
    x86_64|amd64) ARCH="x86_64" ;;
    aarch64|arm64) ARCH="aarch64" ;;
    *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
  esac

  if [ -n "$INSTALL_VERSION" ]; then
    VERSION="$INSTALL_VERSION"
  else
    VERSION=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" | grep '"tag_name"' | head -1 | cut -d'"' -f4)
    VERSION="${VERSION#v}"
  fi
  echo "Installing Vesta v${VERSION}..."

  WORK_DIR=$(mktemp -d)
  trap 'rm -rf "$WORK_DIR"' EXIT

  # Download checksums for verification
  CHECKSUMS="$WORK_DIR/checksums.txt"
  curl -fsSL -o "$CHECKSUMS" "https://github.com/${REPO}/releases/download/v${VERSION}/checksums.txt" 2>/dev/null || true

  verify_checksum() {
    local file="$1"
    local artifact="$2"
    if [ -f "$CHECKSUMS" ]; then
      local expected
      expected=$(grep "  ${artifact}$" "$CHECKSUMS" | cut -d' ' -f1 || true)
      if [ -n "$expected" ]; then
        local actual
        actual=$(sha256sum "$file" 2>/dev/null || shasum -a 256 "$file" | cut -d' ' -f1)
        actual=$(echo "$actual" | cut -d' ' -f1)
        if [ "$actual" != "$expected" ]; then
          echo "Checksum verification failed for $artifact"
          echo "  expected: $expected"
          echo "  got:      $actual"
          exit 1
        fi
      fi
    fi
  }

  PATH_UPDATED=""

  ensure_path() {
    local bin_dir="$HOME/.local/bin"
    case ":$PATH:" in
      *":$bin_dir:"*) return ;;
    esac

    local line='export PATH="$HOME/.local/bin:$PATH"'
    for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
      if [ -f "$rc" ] && ! grep -qF '.local/bin' "$rc"; then
        echo "" >> "$rc"
        echo "# Added by Vesta installer" >> "$rc"
        echo "$line" >> "$rc"
        echo "Added $bin_dir to PATH in $(basename "$rc")"
        PATH_UPDATED=1
      fi
    done

    export PATH="$bin_dir:$PATH"
  }

  install_cli() {
    case "$OS" in
      darwin)
        case "$ARCH" in
          x86_64) local rust_target="x86_64-apple-darwin" ;;
          aarch64) local rust_target="aarch64-apple-darwin" ;;
        esac
        ;;
      linux)
        case "$ARCH" in
          x86_64) local rust_target="x86_64-unknown-linux-gnu" ;;
          aarch64) local rust_target="aarch64-unknown-linux-gnu" ;;
        esac
        ;;
    esac

    local artifact="vesta-${rust_target}.tar.gz"
    echo "Downloading vesta CLI..."
    curl -fsSL -o "$WORK_DIR/vesta.tar.gz" "https://github.com/${REPO}/releases/download/v${VERSION}/${artifact}"
    verify_checksum "$WORK_DIR/vesta.tar.gz" "$artifact"
    tar -xzf "$WORK_DIR/vesta.tar.gz" -C "$WORK_DIR"

    local bin_dir="$HOME/.local/bin"
    mkdir -p "$bin_dir"
    install -m 755 "$WORK_DIR/vesta" "$bin_dir/vesta"
    echo "  ✓ vesta CLI → $bin_dir/vesta"
    ensure_path
  }

  check_docker_snapshotter() {
    if ! command -v docker >/dev/null 2>&1; then
      return
    fi
    local driver
    driver=$(docker info --format '{{.Driver}}' 2>/dev/null || true)
    if [ "$driver" = "overlayfs" ]; then
      echo ""
      echo "WARNING: docker is using the containerd snapshotter (storage driver: overlayfs)."
      echo "This corrupts multi-layer image extraction on Docker 29+ and will cause vesta to"
      echo "fail with 'exec format error'."
      echo ""
      echo "Fix: add the following to /etc/docker/daemon.json and restart docker:"
      echo ""
      echo '  {'
      echo '    "features": { "containerd-snapshotter": false },'
      echo '    "storage-driver": "overlay2"'
      echo '  }'
      echo ""
      echo "Then run: sudo systemctl restart docker"
      echo ""
    fi
  }

  install_vestad() {
    case "$ARCH" in
      x86_64) local rust_target="x86_64-unknown-linux-gnu" ;;
      aarch64) local rust_target="aarch64-unknown-linux-gnu" ;;
    esac

    local artifact="vestad-${rust_target}.tar.gz"
    echo "Downloading vestad server..."
    curl -fsSL -o "$WORK_DIR/vestad.tar.gz" "https://github.com/${REPO}/releases/download/v${VERSION}/${artifact}"
    verify_checksum "$WORK_DIR/vestad.tar.gz" "$artifact"
    tar -xzf "$WORK_DIR/vestad.tar.gz" -C "$WORK_DIR"

    local bin_dir="$HOME/.local/bin"
    mkdir -p "$bin_dir"
    install -m 755 "$WORK_DIR/vestad" "$bin_dir/vestad"
    echo "  ✓ vestad server → $bin_dir/vestad"
    ensure_path
    check_docker_snapshotter
  }

  install_app_linux() {
    if command -v apt-get >/dev/null 2>&1; then
      case "$ARCH" in
        x86_64) local pkg_arch="amd64" ;;
        aarch64) local pkg_arch="arm64" ;;
      esac
      local artifact="Vesta_${VERSION}_${pkg_arch}.deb"
      echo "Downloading desktop app (DEB)..."
      curl -fsSL -o "$WORK_DIR/vesta.deb" "https://github.com/${REPO}/releases/download/v${VERSION}/${artifact}"
      verify_checksum "$WORK_DIR/vesta.deb" "$artifact"
      sudo dpkg -i "$WORK_DIR/vesta.deb"
    elif command -v rpm >/dev/null 2>&1; then
      case "$ARCH" in
        x86_64) local pkg_arch="x86_64" ;;
        aarch64) local pkg_arch="aarch64" ;;
      esac
      local artifact="Vesta-${VERSION}-1.${pkg_arch}.rpm"
      echo "Downloading desktop app (RPM)..."
      curl -fsSL -o "$WORK_DIR/vesta.rpm" "https://github.com/${REPO}/releases/download/v${VERSION}/${artifact}"
      verify_checksum "$WORK_DIR/vesta.rpm" "$artifact"
      sudo rpm -U --force "$WORK_DIR/vesta.rpm"
    else
      echo "  ⚠ No supported package manager (apt-get/rpm), skipping desktop app"
      return
    fi
    echo "  ✓ Vesta desktop app"
  }

  install_app_macos() {
    local artifact="Vesta_${VERSION}_${ARCH}.dmg"
    local dmg_path="$WORK_DIR/Vesta.dmg"
    echo "Downloading desktop app (DMG)..."

    # Map arch for DMG filename
    case "$ARCH" in
      x86_64) artifact="Vesta_${VERSION}_x64.dmg" ;;
      aarch64) artifact="Vesta_${VERSION}_aarch64.dmg" ;;
    esac

    curl -fsSL -o "$dmg_path" "https://github.com/${REPO}/releases/download/v${VERSION}/${artifact}"
    verify_checksum "$dmg_path" "$artifact"

    local mount_point
    mount_point=$(hdiutil attach "$dmg_path" -nobrowse -noautoopen 2>/dev/null | grep -o '/Volumes/.*' | head -1)
    if [ -d "$mount_point/Vesta.app" ]; then
      rm -rf /Applications/Vesta.app
      cp -R "$mount_point/Vesta.app" /Applications/
      hdiutil detach "$mount_point" -quiet
      echo "  ✓ Vesta desktop app → /Applications/Vesta.app"
    else
      hdiutil detach "$mount_point" -quiet 2>/dev/null || true
      echo "  ⚠ Could not find Vesta.app in DMG, skipping"
    fi
  }

  has_gui() {
    case "$OS" in
      darwin) return 0 ;;
      linux) [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ] ;;
      *) return 1 ;;
    esac
  }

  echo ""

  # Validate explicit flags for the current platform
  if [ -n "$EXPLICIT_FLAGS" ]; then
    if [ -n "$INSTALL_SERVER" ] && [ "$OS" != "linux" ]; then
      echo "Error: --server is only available on Linux"; exit 1
    fi
    if [ -n "$INSTALL_APP" ] && ! has_gui; then
      echo "Error: --app requires a GUI (DISPLAY or WAYLAND_DISPLAY)"; exit 1
    fi
  fi

  case "$OS" in
    linux)
      [ -n "$INSTALL_CLI" ] && install_cli
      [ -n "$INSTALL_SERVER" ] && install_vestad
      [ -n "$INSTALL_APP" ] && has_gui && install_app_linux
      ;;
    darwin)
      [ -n "$INSTALL_CLI" ] && install_cli
      [ -n "$INSTALL_APP" ] && has_gui && install_app_macos
      ;;
    *)
      echo "Unsupported OS: $OS"
      echo "Download manually from: https://github.com/${REPO}/releases/latest"
      exit 1
      ;;
  esac

  echo ""
  echo "Done! Get started:"
  if [ "$OS" = "linux" ]; then
    echo "  vestad              # Install systemd service and start"
    echo "  vesta connect       # Connect the CLI"
  else
    echo "  vesta connect <host>#<key>   # Connect to a remote vestad"
  fi
  if has_gui; then
    echo "  Open Vesta app and connect to your server"
  fi
  if [ -n "$PATH_UPDATED" ]; then
    echo ""
    echo "NOTE: Run 'source ~/.bashrc' or open a new terminal first."
  fi
}

main "$@"
