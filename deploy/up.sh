#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
  cp .env.example .env
fi
docker compose up -d --build
echo "Scam Shield is serving on port 80."
echo "Point the GoDaddy domain at this Vultr host, set DOMAIN in .env to that name, then run docker compose up -d."
echo "Record a backup demo on the venue network before judging."
