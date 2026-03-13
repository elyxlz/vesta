#!/usr/bin/env bash
set -euo pipefail

REPO="elyxlz/vesta"
CLI_ONLY=false

for arg in "$@"; do
  case "$arg" in
    --cli) CLI_ONLY=true ;;
    --help|-h)
      echo "Usage: curl -fsSL https://raw.githubusercontent.com/elyxlz/vesta/master/install.sh | bash"
      echo ""
      echo "Options:"
      echo "  --cli    Install CLI only (no desktop app)"
      echo "  --help   Show this help"
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

VERSION=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" | grep '"tag_name"' | head -1 | cut -d'"' -f4)
VERSION="${VERSION#v}"
echo "Installing Vesta v${VERSION}..."

case "$OS" in
  darwin)
    if [ "$CLI_ONLY" = true ]; then
      ARTIFACT="vesta-${ARCH}-apple-darwin.tar.gz"
      echo "Downloading CLI..."
      curl -fsSL -o /tmp/vesta.tar.gz "https://github.com/${REPO}/releases/download/v${VERSION}/${ARTIFACT}"
      tar -xzf /tmp/vesta.tar.gz -C /tmp
      sudo install -m 755 /tmp/vesta /usr/local/bin/vesta
      [ -f /tmp/vfkit ] && sudo install -m 755 /tmp/vfkit /usr/local/bin/vfkit
      rm -f /tmp/vesta.tar.gz /tmp/vesta /tmp/vfkit
      echo "Installed vesta to /usr/local/bin/vesta"
    else
      if [ "$ARCH" = "aarch64" ]; then
        DMG="Vesta_${VERSION}_aarch64.dmg"
      else
        DMG="Vesta_${VERSION}_x64.dmg"
      fi
      echo "Downloading desktop app..."
      curl -fsSL -o "/tmp/${DMG}" "https://github.com/${REPO}/releases/download/v${VERSION}/${DMG}"
      echo "Opening installer..."
      open "/tmp/${DMG}"
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
      curl -fsSL -o /tmp/vesta.tar.gz "https://github.com/${REPO}/releases/download/v${VERSION}/${ARTIFACT}"
      tar -xzf /tmp/vesta.tar.gz -C /tmp
      sudo install -m 755 /tmp/vesta /usr/local/bin/vesta
      rm -f /tmp/vesta.tar.gz /tmp/vesta
      echo "Installed vesta to /usr/local/bin/vesta"
    else
      if [ "$ARCH" = "aarch64" ]; then
        DEB_ARCH="arm64"
      else
        DEB_ARCH="amd64"
      fi

      if command -v dpkg &>/dev/null; then
        DEB="Vesta_${VERSION}_${DEB_ARCH}.deb"
        echo "Downloading desktop app (.deb)..."
        curl -fsSL -o "/tmp/${DEB}" "https://github.com/${REPO}/releases/download/v${VERSION}/${DEB}"
        sudo dpkg -i "/tmp/${DEB}" || sudo apt-get install -f -y
        rm -f "/tmp/${DEB}"
        echo "Installed Vesta desktop app."
      else
        APPIMAGE="Vesta_${VERSION}_${DEB_ARCH}.AppImage"
        echo "Downloading desktop app (AppImage)..."
        mkdir -p "$HOME/.local/bin"
        curl -fsSL -o "$HOME/.local/bin/Vesta.AppImage" "https://github.com/${REPO}/releases/download/v${VERSION}/${APPIMAGE}"
        chmod +x "$HOME/.local/bin/Vesta.AppImage"
        echo "Installed to ~/.local/bin/Vesta.AppImage"
      fi
    fi
    ;;
  *)
    echo "Unsupported OS: $OS"
    echo "Download manually from: https://github.com/${REPO}/releases/latest"
    exit 1
    ;;
esac

echo "Done! Run 'vesta --help' to get started."
