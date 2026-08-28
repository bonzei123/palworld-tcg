# Palworld TCG — lokaler Kartenkatalog

Private Katalog-App für das Palworld Trading Card Game. Läuft auf einem Synology NAS in Docker: SQLite, lokale Bilder, Nutzerkonten für Sammlung und Decks, HTML-Import und ein Regel-Chat über Gemini.

Es wird **nichts von einer Website geladen**. Du erstellst die HTML-Datei selbst und importierst sie im Admin.

## Start (lokal)

```bash
docker compose up -d --build
```

Im LAN: `http://NAS-IP:8585`

Admin-Passwort: Umgebungsvariable `ADMIN_PASSWORD` (Standard: `palworld`). Spieler legen unter `/konto` ein eigenes Konto an (Sammlung + Deckbuilder).

## Auto-Deploy aufs Synology

Bei jedem Push auf `main` baut GitHub Actions ein Image (`linux/amd64` und `arm64`) und legt es nach `ghcr.io/bonzei123/palworld-tcg`. Die Datenbank und Bilder bleiben im Volume `./data` — ein Image-Update überschreibt die Sammlung nicht.

**Empfohlen:** Watchtower auf dem NAS holt das neue Image selbst. GitHub muss das NAS nicht erreichen (kein Port-Forward für SSH).

### 1. Einmalig auf GitHub

- Repo → **Settings → Actions → General**: Workflows dürfen Packages schreiben (Standard bei `GITHUB_TOKEN` + `packages: write` im Workflow).
- Nach dem ersten erfolgreichen Workflow: **Packages** → `palworld-tcg` → Package settings → dem GitHub-Account Leserecht geben, mit dem sich das NAS anmeldet.

### 2. Einmalig auf dem NAS

Ordner z. B. `/volume1/docker/palworld-tcg` mit `docker-compose.yml` und `.env` (von `.env.example` kopieren, Passwort und `SECRET_KEY` setzen).

Privates GHCR-Login (Personal Access Token mit `read:packages`):

```bash
echo DEIN_TOKEN | docker login ghcr.io -u GITHUB_USERNAME --password-stdin
```

Erstes Starten (zieht das Image, startet die App **und** Watchtower):

```bash
cd /volume1/docker/palworld-tcg
docker compose pull
docker compose up -d
```

Watchtower prüft alle 2 Minuten, ob `:latest` neu ist, zieht es und startet den Container neu.

Falls `config.json` nicht unter `/root/.docker/` liegt, in der `.env` setzen: `DOCKER_CONFIG_FILE=/var/services/homes/DEINUSER/.docker/config.json`.

Ohne Watchtower geht auch eine **DSM-Aufgabe** (Aufgabenplaner, alle 2 Minuten, Benutzer mit Docker-Recht):

```bash
/volume1/docker/palworld-tcg/deploy/nas-update.sh
```

(`chmod +x deploy/nas-update.sh`)

### 3. Optional: sofort per SSH nach dem Push

Nur wenn GitHub das NAS per SSH erreicht (Tailscale, VPN, nicht Port 22 ins Internet). Unter **Settings → Secrets and variables → Actions**:

| Art | Name | Beispiel |
| --- | --- | --- |
| Variable | `NAS_HOST` | `100.x.x.x` (Tailscale) |
| Variable | `NAS_USER` | `florian` |
| Variable | `NAS_COMPOSE_DIR` | `/volume1/docker/palworld-tcg` |
| Secret | `NAS_SSH_KEY` | privater Schlüssel ohne Passphrase |

Solange `NAS_HOST` leer ist, überspringt der Deploy-Job — Watchtower reicht.

## Was die App kann

- **Katalog** mit Suche und Filtern (Typ, Farbe, Seltenheit, Edition, Attribute, Aptitudes wie Kindling/Dragon)
- **Sammlung** pro Nutzer: Habe ich / Brauche ich / Anzahl, Export als CSV oder JSON
- **Deckbuilder** mit Kostenkurve und Farbcheck (Hinweise, keine inoffiziellen Hard-Locks)
- **Vergleich** RR / OSR / SSP derselben Karte unter `/compare/{id}`
- **Regel-Chat** (Gemini): Kontext aus Regel-PDF, Errata/Banlist und Katalog. Gleiche Fragen kommen aus dem Cache und kosten keine Tokens
- **PWA**: Install-Icon, Offline-Katalog (`/offline`)
- **Admin**: HTML-Import, Bilder-ZIP, Gemini-Key in der DB, Regeln, Errata/Banlist

## NAS, LAN, HTTPS

Die App ist für **LAN oder VPN** gedacht, nicht fürs offene Internet.

- Gemini-API-Key liegt nur in `data/palworld.db` (`settings.gemini_api_key`), nicht in der Compose-Datei.
- Nach außen Port **8585** (Compose mappt `8585:8080`). Im Container bleibt 8080. DSM **Reverse Proxy** mit HTTPS, wenn du eine Domain willst.
- Hinter dem Proxy in der `.env` `HTTPS_ONLY=true` setzen (Secure-Cookies). Die App selbst spricht intern HTTP; HTTPS terminiert auf dem Reverse Proxy.
- Wenn das NAS **kein Internet** hat, funktioniert der Katalog lokal. Der Chat beantwortet dann nur noch **gecachte** Fragen.

Reverse-Proxy-Hinweise (DSM):

- Quelle: `https://katalog.lan` (oder deine Zertifikats-Domain)
- Ziel: `http://127.0.0.1:8585`
- Header: `X-Forwarded-Proto` = `https`, `X-Forwarded-For` durchreichen
- WebSocket nicht nötig

## Errata / Banlist

Unter Admin → Einstellungen eine Datei hochladen (PDF, TXT oder MD). Sie liegt als eigene Datei in `data/rules/` und wird **im Chat-Kontext** mitgegeben, vorrangig vor dem allgemeinen Regelheft.

## Backup (Hyper Backup)

Regelmäßig das Verzeichnis **`./data`** sichern (Hyper Backup, rsync, Snapshot):

- `palworld.db` (+ `-wal`/`-shm` falls vorhanden) — Karten, Nutzer, Sammlung, Decks, Chat-Cache, Gemini-Key
- `images/` — Kartenbilder
- `rules/` — Regel-PDF und Errata

Ohne `data/` sind Konten und der Katalog weg. Ein Dump der laufenden DB ist nicht nötig, wenn der Container kurz ruht oder WAL mitkopiert wird.

## Daten

Volume `./data` bzw. `DATA_DIR`:

- `palworld.db` — SQLite inkl. FTS5
- `images/` — hochgeladene Art
- `rules/` — Regeln und Errata
