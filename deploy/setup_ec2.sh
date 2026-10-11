#!/usr/bin/env bash
# Run ON the EC2 instance after cloning the repo to /home/ubuntu/routing_backend
# Usage:
#   cd /home/ubuntu/routing_backend
#   bash deploy/setup_ec2.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

echo "==> Installing system packages (may need sudo password)"
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nginx git

if [[ ! -d venv ]]; then
  echo "==> Creating venv"
  python3 -m venv venv
fi

echo "==> Installing Python deps"
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [[ ! -f .env ]]; then
  echo "==> Creating .env from .env.example — EDIT IT before going live"
  cp .env.example .env
  echo "    Edit: nano $APP_DIR/.env"
  echo "    Set DJANGO_DEBUG=False and DJANGO_ALLOWED_HOSTS=<your-ec2-ip-or-domain>"
fi

echo "==> migrate + collectstatic"
python manage.py migrate --noinput
python manage.py collectstatic --noinput

echo "==> Installing systemd unit"
sudo cp deploy/routing.service /etc/systemd/system/routing.service
sudo systemctl daemon-reload
sudo systemctl enable routing
sudo systemctl restart routing

echo "==> Installing Nginx site (edit server_name if needed)"
TMP="$(mktemp)"
# default server_name to instance public hostname if available
PUBLIC_HOST="$(curl -s --max-time 2 http://169.254.169.254/latest/meta-data/public-ipv4 || true)"
if [[ -z "$PUBLIC_HOST" ]]; then
  PUBLIC_HOST="_"
fi
sed "s/YOUR_EC2_PUBLIC_IP_OR_DOMAIN/${PUBLIC_HOST}/g" deploy/nginx.conf > "$TMP"
sudo cp "$TMP" /etc/nginx/sites-available/routing
rm -f "$TMP"
sudo ln -sf /etc/nginx/sites-available/routing /etc/nginx/sites-enabled/routing
sudo rm -f /etc/nginx/sites-enabled/default

# Allow nginx (www-data) to reach the ubuntu home socket
sudo usermod -a -G ubuntu www-data || true
sudo chmod 710 /home/ubuntu || true

sudo nginx -t
sudo systemctl restart nginx

echo ""
echo "==> Done."
echo "    Health: http://${PUBLIC_HOST}/api/health"
echo "    Status: sudo systemctl status routing"
echo "    Logs:   sudo journalctl -u routing -f"
