#!/usr/bin/env bash
# One-time preparation of a fresh Oracle Cloud Ubuntu (aarch64) VM for LOCAH.
# Run on the VM as the default `ubuntu` user:  bash infra/deploy/oracle/setup.sh
#
# Installs Docker and git from Ubuntu's own packages, opens ports 80/443 in the
# host firewall (Oracle's Ubuntu images reject everything but SSH), and adds swap
# so the Next.js builds never run out of memory. It writes no secrets.
set -euo pipefail

sudo apt-get update -y
sudo apt-get install -y docker.io docker-compose-v2 git iptables-persistent
sudo usermod -aG docker "$USER"
sudo systemctl enable --now docker

# Oracle images end INPUT with a REJECT rule: accept web traffic before it.
for rule in "-p tcp --dport 80" "-p tcp --dport 443" "-p udp --dport 443"; do
  # shellcheck disable=SC2086
  sudo iptables -C INPUT -m state --state NEW $rule -j ACCEPT 2>/dev/null \
    || sudo iptables -I INPUT 5 -m state --state NEW $rule -j ACCEPT
done
sudo netfilter-persistent save

if [ ! -f /swapfile ]; then
  sudo fallocate -l 4G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

cd "$(dirname "$0")"
for f in public.env server.env; do
  if [ ! -f "$f" ]; then
    cp "$f.example" "$f"
    chmod 600 "$f"
    echo "created $PWD/$f — fill it in before starting"
  fi
done
echo "Done. Log out and back in (docker group), fill public.env and server.env, then:"
echo "  cd $PWD && docker compose --env-file public.env up -d --build"
