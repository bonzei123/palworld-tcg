# Palworld TCG — lokaler Kartenkatalog

Private Katalog-App für das Palworld Trading Card Game. Läuft auf einem Synology NAS in Docker: SQLite, lokale Bilder, Nutzerkonten für Sammlung und Decks, HTML-Import und ein Regel-Chat über Gemini.

Es wird **nichts von einer Website geladen**. Du erstellst die HTML-Datei selbst und importierst sie im Admin.

## Start

```bash
docker compose up -d --build
```

Im LAN: `http://NAS-IP:8080`

Admin-Passwort: Umgebungsvariable `ADMIN_PASSWORD` (Standard: `palworld`). Spieler legen unter `/konto` ein eigenes Konto an (Sammlung + Deckbuilder).

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
- Port 8080 nur intern binden. Nach außen: DSM **Reverse Proxy** mit HTTPS.
- Hinter dem Proxy in der Compose `HTTPS_ONLY=true` setzen (Secure-Cookies). Die App selbst spricht intern HTTP; HTTPS terminiert auf dem Reverse Proxy.
- Wenn das NAS **kein Internet** hat, funktioniert der Katalog lokal. Der Chat beantwortet dann nur noch **gecachte** Fragen.

Reverse-Proxy-Hinweise (DSM):

- Quelle: `https://katalog.lan` (oder deine Zertifikats-Domain)
- Ziel: `http://127.0.0.1:8080`
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
