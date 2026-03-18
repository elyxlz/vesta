#!/usr/bin/env bash
set -euo pipefail

main() {
  REPO="elyxlz/vesta"
  CLI_ONLY=false
  INSTALL_VERSION=""

  for arg in "$@"; do
    case "$arg" in
      --cli) CLI_ONLY=true ;;
      --version=*) INSTALL_VERSION="${arg#--version=}" ;;
      --help|-h)
        echo "Usage: curl -fsSL https://raw.githubusercontent.com/elyxlz/vesta/master/install.sh | bash"
        echo ""
        echo "Options:"
        echo "  --cli              Install CLI only (no desktop app)"
        echo "  --version=X.Y.Z   Install a specific version"
        echo "  --help             Show this help"
        exit 0
        ;;
    esac
  done

  OS=$(uname -s | tr '[:upper:]' '[:lower:]')
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

  # Download checksums once for verification
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
        actual=$(sha256sum "$file" | cut -d' ' -f1)
        if [ "$actual" != "$expected" ]; then
          echo "Checksum verification failed for $artifact"
          echo "  expected: $expected"
          echo "  got:      $actual"
          exit 1
        fi
      fi
    fi
  }

  install_cli_to_path() {
    local src="$1"
    local bin_dir="$HOME/.local/bin"
    mkdir -p "$bin_dir"
    install -m 755 "$src" "$bin_dir/vesta"
    echo "Installed vesta to $bin_dir/vesta"
    case ":$PATH:" in
      *":$bin_dir:"*) ;;
      *) echo "WARNING: $bin_dir is not in your PATH. Add it with:"
         echo "  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
    esac
  }

  case "$OS" in
    darwin)
      if [ "$CLI_ONLY" = true ]; then
        ARTIFACT="vesta-${ARCH}-apple-darwin.tar.gz"
        echo "Downloading CLI..."
        curl -fsSL -o "$WORK_DIR/vesta.tar.gz" "https://github.com/${REPO}/releases/download/v${VERSION}/${ARTIFACT}"
        verify_checksum "$WORK_DIR/vesta.tar.gz" "$ARTIFACT"
        tar -xzf "$WORK_DIR/vesta.tar.gz" -C "$WORK_DIR"
        install_cli_to_path "$WORK_DIR/vesta"
        if [ -f "$WORK_DIR/vfkit" ]; then
          install -m 755 "$WORK_DIR/vfkit" "$HOME/.local/bin/vfkit"
        fi
      else
        if [ "$ARCH" = "aarch64" ]; then
          DMG="Vesta_${VERSION}_aarch64.dmg"
        else
          DMG="Vesta_${VERSION}_x64.dmg"
        fi
        echo "Downloading desktop app..."
        curl -fsSL -o "$WORK_DIR/${DMG}" "https://github.com/${REPO}/releases/download/v${VERSION}/${DMG}"
        verify_checksum "$WORK_DIR/${DMG}" "$DMG"
        xattr -cr "$WORK_DIR/${DMG}"
        echo "Opening installer..."
        open "$WORK_DIR/${DMG}"
        echo "Drag Vesta to Applications to complete installation."
      fi
      ;;
    linux)
      if [ "$CLI_ONLY" = false ] && [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
        echo "No display detected, installing CLI only. Use --cli to suppress this message."
        CLI_ONLY=true
      fi

      if [ "$CLI_ONLY" = true ]; then
        case "$ARCH" in
          x86_64) RUST_TARGET="x86_64-unknown-linux-gnu" ;;
          aarch64) RUST_TARGET="aarch64-unknown-linux-gnu" ;;
        esac
        ARTIFACT="vesta-${RUST_TARGET}.tar.gz"
        echo "Downloading CLI..."
        curl -fsSL -o "$WORK_DIR/vesta.tar.gz" "https://github.com/${REPO}/releases/download/v${VERSION}/${ARTIFACT}"
        verify_checksum "$WORK_DIR/vesta.tar.gz" "$ARTIFACT"
        tar -xzf "$WORK_DIR/vesta.tar.gz" -C "$WORK_DIR"
        install_cli_to_path "$WORK_DIR/vesta"
      else
        if command -v apt-get >/dev/null 2>&1; then
          PKG_TYPE="deb"
        elif command -v rpm >/dev/null 2>&1; then
          PKG_TYPE="rpm"
        else
          echo "No supported package manager found (apt-get or rpm required)"
          exit 1
        fi

        if [ "$PKG_TYPE" = "rpm" ]; then
          case "$ARCH" in
            x86_64) PKG_ARCH="x86_64" ;;
            aarch64) PKG_ARCH="aarch64" ;;
          esac
          ARTIFACT="Vesta-${VERSION}-1.${PKG_ARCH}.rpm"
          echo "Downloading desktop app (RPM)..."
          curl -fsSL -o "$WORK_DIR/vesta.rpm" "https://github.com/${REPO}/releases/download/v${VERSION}/${ARTIFACT}"
          verify_checksum "$WORK_DIR/vesta.rpm" "$ARTIFACT"
          sudo rpm -U --force "$WORK_DIR/vesta.rpm"
        else
          case "$ARCH" in
            x86_64) PKG_ARCH="amd64" ;;
            aarch64) PKG_ARCH="arm64" ;;
          esac
          ARTIFACT="Vesta_${VERSION}_${PKG_ARCH}.deb"
          echo "Downloading desktop app (DEB)..."
          curl -fsSL -o "$WORK_DIR/vesta.deb" "https://github.com/${REPO}/releases/download/v${VERSION}/${ARTIFACT}"
          verify_checksum "$WORK_DIR/vesta.deb" "$ARTIFACT"
          sudo dpkg -i "$WORK_DIR/vesta.deb"
        fi

        echo "Installed Vesta desktop app."
        echo "Launch it from your app menu or by running: vesta-app"
      fi
      ;;
    *)
      echo "Unsupported OS: $OS"
      echo "Download manually from: https://github.com/${REPO}/releases/latest"
      exit 1
      ;;
  esac

  echo "Done! Run 'vesta --help' to get started."
}

main "$@"
