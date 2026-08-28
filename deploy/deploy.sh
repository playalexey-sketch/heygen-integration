#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# HeyGen Integration — one-shot deploy script (Debian/Ubuntu/RHEL/Fedora VPS)
#
# Usage (as root):
#   bash deploy.sh --key=ВАШ_HEYGEN_API_KEY [--domain=your.domain.tld]
#
# What it does:
#   1. Installs python3, venv, pip, nginx
#   2. Downloads the app from GitHub (branch with this script)
#   3. Creates /opt/heygen-integration/{app,venv,.env} + systemd services
#   4. Configures nginx: / (UI), /api/ + /docs (FastAPI), websockets
#   5. Opens 80/443 in local firewall (if ufw/firewalld present)
#   6. Optionally installs HTTPS (certbot) when --domain is given
#
# Re-runnable: safe to execute again to update the code.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

BASE=/opt/heygen-integration
APP="$BASE/app"
VENV="$BASE/venv"
ENVFILE="$BASE/.env"
REPO="playalexey-sketch/heygen-integration"
BRANCH="arena/01a046c0-heygen-integration"
SERV_USER="heygen"

log()  { echo -e "\n\033[1;32m==> $*\033[0m"; }
warn() { echo -e "\033[1;33m[!] $*\033[0m"; }
die()  { echo -e "\033[1;31m[x] $*\033[0m" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "Run as root (use sudo)."

# ── Parse arguments ──────────────────────────────────────────────────────────
DOMAIN=""
API_KEY="${HEYGEN_API_KEY:-}"
for a in "$@"; do
  case "$a" in
    --domain=*) DOMAIN="${a#*=}" ;;
    --key=*)    API_KEY="${a#*=}" ;;
    -h|--help)  grep '^# ' "$0" | sed 's/^# //'; exit 0 ;;
    *) echo "Unknown argument: $a (expected --key=..., --domain=...)" >&2; exit 2 ;;
  esac
done

# ── 1. System packages ───────────────────────────────────────────────────────
. /etc/os-release 2>/dev/null || true
DISTRO="${ID:-unknown}"
log "Distro: ${PRETTY_NAME:-$DISTRO} — installing system packages"
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
      python3 python3-venv python3-pip nginx curl ca-certificates
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y -q python3 python3-pip nginx curl ca-certificates
elif command -v yum >/dev/null 2>&1; then
  yum install -y -q python3 python3-pip nginx curl ca-certificates
elif command -v apk >/dev/null 2>&1; then
  apk add --no-cache python3 py3-pip nginx curl ca-certificates
else
  die "No supported package manager (apt/dnf/yum/apk) found."
fi

PY="$(command -v python3)"
"$PY" - <<'EOF' || die "Python 3.9+ required"
import sys
assert sys.version_info >= (3, 9), f"Python {sys.version} too old"
print(f"Python {sys.version.split()[0]} OK")
EOF

# ── 2. Download code from GitHub ─────────────────────────────────────────────
TARBALL="https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH"
log "Downloading app code from GitHub ($BRANCH)"
EXTRACT_DIR="$(mktemp -d)"
trap 'rm -rf "$EXTRACT_DIR"' EXIT
curl -fsSL --retry 3 --max-time 300 "$TARBALL" -o "$EXTRACT_DIR/src.tgz" \
  || die "GitHub download failed. If GitHub is blocked on this server, tell the operator to transfer the code manually (or use a mirror)."
mkdir -p "$EXTRACT_DIR/out"
tar -xzf "$EXTRACT_DIR/src.tgz" -C "$EXTRACT_DIR/out" --strip-components=1
[ -f "$EXTRACT_DIR/out/requirements.txt" ] || die "Unexpected tarball layout (requirements.txt not found)."

if [ -d "$APP" ]; then
  log "Existing installation found — updating"
  mv "$APP" "$EXTRACT_DIR/old-app" || true
  mv "$EXTRACT_DIR/old-app/.env" "$ENVFILE" 2>/dev/null || true
fi
mv "$EXTRACT_DIR/out" "$APP"

# ── 3. Virtualenv + dependencies ─────────────────────────────────────────────
log "Creating virtualenv and installing Python dependencies (may take a few minutes)"
"$PY" -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$APP/requirements.txt"

# ── 4. .env ──────────────────────────────────────────────────────────────────
log "Preparing $ENVFILE"
if [ ! -f "$ENVFILE" ]; then
  cp "$APP/.env.example" "$ENVFILE"
fi
# Bind to localhost only (nginx is the public entry point)
if grep -q '^HOST=' "$ENVFILE"; then
  grep -v '^HOST=' "$ENVFILE" > "$ENVFILE.tmp" && printf 'HOST=127.0.0.1\n' | cat - "$ENVFILE.tmp" > "$ENVFILE" && rm -f "$ENVFILE.tmp"
else
  printf 'HOST=127.0.0.1\n' >> "$ENVFILE"
fi
if [ -n "$API_KEY" ]; then
  grep -v '^HEYGEN_API_KEY=' "$ENVFILE" > "$ENVFILE.tmp" || true
  mv "$ENVFILE.tmp" "$ENVFILE"
  printf 'HEYGEN_API_KEY=%s\n' "$API_KEY" >> "$ENVFILE"
  log "HEYGEN_API_KEY set in $ENVFILE"
else
  warn "HEYGEN_API_KEY NOT provided. API service will stay stopped until you add it."
fi

# ── 5. Service user + permissions ────────────────────────────────────────────
id "$SERV_USER" >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin -d "$BASE" "$SERV_USER"
chown -R "$SERV_USER":"$SERV_USER" "$BASE"
chmod 600 "$ENVFILE"

# ── 6. systemd units ─────────────────────────────────────────────────────────
log "Installing systemd services"
cat > /etc/systemd/system/heygen-api.service <<UNIT
[Unit]
Description=HeyGen Integration API (FastAPI)
After=network.target

[Service]
User=$SERV_USER
WorkingDirectory=$APP
EnvironmentFile=-$ENVFILE
ExecStart=$VENV/bin/uvicorn api.server:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/heygen-ui.service <<UNIT
[Unit]
Description=HeyGen Integration UI (Streamlit)
After=network.target

[Service]
User=$SERV_USER
WorkingDirectory=$APP
EnvironmentFile=-$ENVFILE
ExecStart=$VENV/bin/streamlit run ui/app.py \
  --server.port 8501 \
  --server.address 127.0.0.1 \
  --server.headless true \
  --browser.gatherUsageStats false
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

# ── 7. nginx ─────────────────────────────────────────────────────────────────
log "Configuring nginx"
if [ -d /etc/nginx/sites-enabled ]; then
  NGINX_SITE=/etc/nginx/sites-available/heygen.conf
  ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/heygen.conf
  rm -f /etc/nginx/sites-enabled/default
else
  NGINX_SITE=/etc/nginx/conf.d/heygen.conf
fi
cat > "$NGINX_SITE" <<'NGX'
# HeyGen Integration — public entry point
upstream heygen_api { server 127.0.0.1:8000; }
upstream heygen_ui  { server 127.0.0.1:8501; }

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    client_max_body_size 200M;

    # FastAPI: API routes, swagger docs, health
    location ~ ^/(api/|docs|openapi\.json|health) {
        proxy_pass http://heygen_api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Streamlit UI (needs websocket upgrade)
    location / {
        proxy_pass http://heygen_ui;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
NGX

# ── 8. Local firewall (best effort) ──────────────────────────────────────────
if command -v ufw >/dev/null 2>&1 && ufw is active >/dev/null 2>&1; then
  log "Opening 80/443 in ufw"
  ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
fi
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active firewalld >/dev/null 2>&1; then
  log "Opening 80/443 in firewalld"
  firewall-cmd --permanent --add-service=http --add-service=https >/dev/null
  firewall-cmd --reload >/dev/null
fi

# ── 9. Start services ────────────────────────────────────────────────────────
systemctl daemon-reload
nginx -t >/dev/null
systemctl enable nginx >/dev/null 2>&1
systemctl restart nginx

systemctl enable heygen-ui >/dev/null 2>&1
systemctl restart heygen-ui
sleep 2
if systemctl is-active --quiet heygen-ui; then
  log "UI service is running (port 8501)"
else
  warn "UI service failed to start — check: journalctl -u heygen-ui -n 50"
fi

if [ -n "$API_KEY" ]; then
  systemctl enable heygen-api >/dev/null 2>&1
  systemctl restart heygen-api
  sleep 3
  if curl -fs --max-time 10 http://127.0.0.1:8000/health >/dev/null 2>&1; then
    log "API service is running and healthy (port 8000)"
  else
    warn "API service did not become healthy — check: journalctl -u heygen-api -n 50"
  fi
else
  systemctl disable --now heygen-api 2>/dev/null || true
fi

# ── 10. HTTPS (optional) ─────────────────────────────────────────────────────
if [ -n "$DOMAIN" ]; then
  log "Installing HTTPS for $DOMAIN (certbot)"
  if command -v apt-get >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq certbot python3-certbot-nginx
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y -q certbot python3-certbot-nginx
  fi
  EMAIL="admin@$DOMAIN"
  if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect 2>&1 | tail -5; then
    log "HTTPS enabled for $DOMAIN"
  else
    warn "certbot failed — usually the domain does not point to this server's IP yet. After DNS is set, run: certbot --nginx -d $DOMAIN --redirect"
  fi
fi

# ── 11. Summary ──────────────────────────────────────────────────────────────
PUBIP="$(curl -fs --max-time 8 https://api.ipify.org 2>/dev/null || curl -fs --max-time 8 https://ifconfig.me 2>/dev/null || echo '<server-ip>')"
BASE_URL="http://$PUBIP"
[ -n "$DOMAIN" ] && BASE_URL="https://$DOMAIN"

cat <<SUMMARY

════════════════════════════════════════════════════════════════
  DEPLOY FINISHED
════════════════════════════════════════════════════════════════
  UI (Streamlit):   $BASE_URL/
  API (FastAPI):    $BASE_URL/api/v1/...
  Swagger docs:     $BASE_URL/docs
  Health check:     $BASE_URL/health
  Code:             $APP
  Config:           $ENVFILE
  Services:         systemctl status heygen-api heygen-ui

  In the UI sidebar set "API Base URL" to: $BASE_URL

  If the page does not open: open ports 80/443 in the TIMWEB
  panel firewall (Cloud → Server → Firewall), not only locally.

  Useful commands:
    journalctl -u heygen-api -f        # API logs
    journalctl -u heygen-ui -f         # UI logs
    nano $ENVFILE                      # edit config
    systemctl restart heygen-api       # restart after .env change
════════════════════════════════════════════════════════════════
SUMMARY
