# Deploy on AWS EC2

Templates in this folder:

| File | Purpose |
|------|---------|
| `routing.service` | systemd unit for Gunicorn |
| `nginx.conf` | Nginx reverse proxy |
| `setup_ec2.sh` | One-shot installer on a fresh Ubuntu EC2 |

## 1. Launch EC2

- AMI: **Ubuntu 22.04 LTS**
- Type: `t2.micro` / `t3.micro`
- Security group inbound: **22** (your IP), **80** (anywhere), **443** (optional)

## 2. SSH and clone

```bash
ssh -i your-key.pem ubuntu@YOUR_EC2_PUBLIC_IP
git clone https://github.com/Baansheeee/routing_backend.git
cd routing_backend
```

## 3. Run setup script

```bash
bash deploy/setup_ec2.sh
nano .env   # DJANGO_DEBUG=False, ALLOWED_HOSTS=<public-ip>, MAPBOX_TOKEN, CORS…
sudo systemctl restart routing
```

## 4. Verify

```bash
curl http://127.0.0.1/api/health
# or from your browser:
# http://YOUR_EC2_PUBLIC_IP/api/health
```

## 5. Frontend

```env
VITE_API_URL=http://YOUR_EC2_PUBLIC_IP/api
```

Update `.env` on the server:

```env
CORS_ALLOWED_ORIGINS=http://localhost:5173,https://your-frontend.vercel.app
CSRF_TRUSTED_ORIGINS=http://localhost:5173,https://your-frontend.vercel.app
DJANGO_ALLOWED_HOSTS=YOUR_EC2_PUBLIC_IP
```

```bash
sudo systemctl restart routing
```

## Manual install (if you skip the script)

```bash
sudo cp deploy/routing.service /etc/systemd/system/routing.service
sudo systemctl daemon-reload && sudo systemctl enable --now routing

# Edit server_name in nginx.conf, then:
sudo cp deploy/nginx.conf /etc/nginx/sites-available/routing
sudo ln -sf /etc/nginx/sites-available/routing /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl restart nginx
```

## Redeploy after code changes

```bash
cd /home/ubuntu/routing_backend
git pull
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py collectstatic --noinput
sudo systemctl restart routing
```

## Logs

```bash
sudo systemctl status routing
sudo journalctl -u routing -f
sudo tail -f /var/log/nginx/error.log
```

## Optional HTTPS

Point a domain A-record to the Elastic IP, then:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.yourdomain.com
```
