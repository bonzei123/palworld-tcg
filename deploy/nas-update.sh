#!/bin/sh
# DSM-Aufgabe: alle 2–5 Minuten, oder nach einem Push (Watchtower macht dasselbe).
set -eu
cd "$(dirname "$0")/.."
docker compose pull
docker compose up -d --remove-orphans
docker image prune -f >/dev/null 2>&1 || true
