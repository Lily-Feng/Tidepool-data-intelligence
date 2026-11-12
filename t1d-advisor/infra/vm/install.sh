#!/usr/bin/env bash
# Runs ON the VM as root, called by infra/deploy.sh. Idempotent.
#   sudo bash install.sh <unpacked release dir>
# Installs Node (checksum-verified), a locked-down service user, the app under
# /opt/t1d-advisor (read-only to the service), and the systemd unit.
# Secrets are never written to disk: start.mjs reads them from Secret Manager.
set -euo pipefail

SRC="${1:?usage: install.sh <release dir>}"
APP_DIR=/opt/t1d-advisor
NODE_MAJOR=24

echo "== OS packages and automatic security updates"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl xz-utils unattended-upgrades >/dev/null
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "== journald: keep logs local and small"
mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=200M\nMaxRetentionSec=14day\n' > /etc/systemd/journald.conf.d/t1d-advisor.conf
systemctl restart systemd-journald

echo "== Node.js v$NODE_MAJOR (verified against nodejs.org SHASUMS256)"
if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" != "$NODE_MAJOR" ]; then
  case "$(uname -m)" in
    x86_64) ARCH=x64 ;;
    aarch64) ARCH=arm64 ;;
    *) echo "unsupported arch $(uname -m)"; exit 1 ;;
  esac
  BASE="https://nodejs.org/dist/latest-v${NODE_MAJOR}.x"
  TMP="$(mktemp -d)"
  curl -fsSL "$BASE/SHASUMS256.txt" -o "$TMP/SHASUMS256.txt"
  FILE="$(grep -oE "node-v[0-9.]+-linux-${ARCH}\.tar\.xz" "$TMP/SHASUMS256.txt" | head -1)"
  curl -fsSL "$BASE/$FILE" -o "$TMP/$FILE"
  (cd "$TMP" && grep " $FILE\$" SHASUMS256.txt | sha256sum -c -)
  tar -xJf "$TMP/$FILE" -C /usr/local --strip-components=1 --exclude='*/CHANGELOG.md' --exclude='*/README.md' --exclude='*/LICENSE'
  rm -rf "$TMP"
fi
node --version

echo "== service user"
id t1d-advisor >/dev/null 2>&1 || useradd --system --no-create-home --home-dir "$APP_DIR" --shell /usr/sbin/nologin t1d-advisor

echo "== app release"
rm -rf "$APP_DIR.new"
cp -a "$SRC" "$APP_DIR.new"
(cd "$APP_DIR.new" && npm ci --omit=dev --ignore-scripts --no-audit --no-fund --loglevel=error)
chown -R root:t1d-advisor "$APP_DIR.new"
chmod -R u=rwX,g=rX,o= "$APP_DIR.new"
rm -rf "$APP_DIR.prev"
[ -d "$APP_DIR" ] && mv "$APP_DIR" "$APP_DIR.prev"
mv "$APP_DIR.new" "$APP_DIR"

echo "== systemd unit"
install -m 0644 "$APP_DIR/infra/vm/t1d-advisor.service" /etc/systemd/system/t1d-advisor.service
systemctl daemon-reload
systemctl enable t1d-advisor >/dev/null 2>&1
systemctl restart t1d-advisor
sleep 5
systemctl is-active t1d-advisor
journalctl -u t1d-advisor -n 15 --no-pager -o cat
