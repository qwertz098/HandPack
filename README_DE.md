# HandPack (x265 / MKV)

Ein-Fenster-GUI zum Batch-Transcodieren mit ffmpeg.

*(English version: [README.md](README.md))*

## Installation
    pip install PySide6
Benötigte Tools (PATH oder übliche Orte, sonst Hinweis im Fenster):
- ffmpeg / ffprobe (Pflicht)
- dovi_tool (Dolby-Vision-Erhalt; fehlt es: HDR10-Fallback)
- mkvmerge / MKVToolNix (bevorzugter DV-Muxer; fehlt es: ffmpeg-Mux)

## Start
    python main.py

## Funktionen
- Drop-Area (Dateien + Ordner rekursiv) und Klick = Dateidialog
- Analyse: Auflösung, Codec, Bittiefe, Audio-/Subtitle-Streams, HDR10/HDR10+/HLG/DV (Profil)
- Autocrop über 5 Samples, global abschaltbar (Checkbox „Crop-Analyse")
- Option „Min. Crop" (Standard 20 px): Ränder unter diesem Wert je Seite
  ignoriert die Crop-Analyse, damit FullHD/4K pixelgenau bleibt (0 = aus)
- Flacher Fensterkopf: Einstellungen zweireihig, kleine Drop-Area rechts
- Crop pro Zeile per Checkbox deaktivierbar, Wert manuell editierbar (w:h:x:y)
- Rechtsklick-Kontextmenü pro Zeile: Crop neu analysieren, Crop-Vorschau,
  **Qualitäts-Vergleich**, Überschreiben erzwingen, Erneut einreihen,
  Audio-Modus/-bitrate/-kanäle/-DRC pro Spur, Nach oben/unten, Aus Liste
  entfernen
- **Qualitäts-Vergleich** („Qualitäts-Vergleich…" im Kontextmenü): vor
  einem größeren Encode eine freie Matrix aus Auflösungen × CRF-Werten ×
  Tunes an einer einstellbaren Anzahl kurzer Samples testen (1–10,
  Standard 3) mit einstellbarer Dauer je Sample (1–100 s, Standard 10 s),
  über die Laufzeit verteilt. Eine oder mehrere Metriken wählbar:
  **VMAF**, **SSIM**, **PSNR** (alle in einem einzigen ffmpeg-Durchlauf
  pro Sample berechnet, egal wie viele gewählt sind — libvmaf berechnet
  SSIM/PSNR bei Kombination mit VMAF als Nebenprodukt mit, ein
  `split`-basierter Filtergraph kombiniert SSIM+PSNR auch ohne VMAF).
  VMAF braucht libvmaf im ffmpeg; Fallback auf SSIM falls nicht vorhanden.
  Was die drei Metriken bedeuten (Hover über die Checkbox im Dialog zeigt
  denselben Text):
  - **VMAF** (0–100, höher = besser) — Netflix' Wahrnehmungsmetrik,
    trainiert an menschlichen Bewertungen. Bildet am zuverlässigsten ab,
    wie ein echter Betrachter die Qualität wahrnimmt, besonders bei
    Kompressionsartefakten. Empfohlener Standard.
  - **SSIM** (0–1, höher = besser) — vergleicht lokale Struktur/Kontrast
    statt reiner Pixelwerte. Etabliert, korreliert aber schwächer mit
    menschlicher Wahrnehmung als VMAF, besonders bei Blocking-/
    Ringing-Artefakten.
  - **PSNR** (dB, höher = besser) — einfacher, rein pixelweiser
    Differenzvergleich. Schnell, aber am schlechtesten mit tatsächlich
    wahrgenommener Qualität korreliert; nur als grober Zusatzwert
    gedacht, nicht als Hauptentscheidungsgrundlage.

  Ergebnistabelle zeigt Score(s), geschätzte Ausgabegröße und % vom
  Original; **nicht dominierte ("Pareto-optimale") Zeilen werden mit ★
  markiert** — eine Variante lohnt sich nur, wenn keine andere sowohl
  kleiner *als auch* mindestens gleich gut ist. Das ist die praktisch
  richtige Art, das Größe/Qualität-Verhältnis zu beurteilen (die
  Qualitätskurve verläuft nicht linear zur Größe, eine einfache
  Score-pro-MB-Kennzahl wäre irreführend). **Doppelklick auf eine Zeile**
  (auch die Referenzzeile) spielt das Sample bzw. Original ab
  (QtMultimedia) — so lässt sich die Qualität visuell beurteilen statt nur
  den Zahlen zu vertrauen; die Sample-Dateien bleiben bis zum Schließen
  des Dialogs erhalten (nicht sofort nach der Messung gelöscht).
  **Mehrere Zeilen auswählen + „Frames vergleichen"** zeigt Einzelbilder
  aller gewählten Zeilen bei einem wählbaren Zeitpunkt nebeneinander
  (Standard: Mitte des Samples) — hilfreich, um Artefakte zu erkennen,
  die ein einzelner Gesamt-Score verbergen könnte. Ein **„Sample"-Dropdown**
  neben dem Zeit-Schieberegler schaltet alle sichtbaren Zellen gleichzeitig
  zwischen den getesteten Sample-Zeitpunkten um (z. B. 20/50/80 % der
  Laufzeit), unabhängig vom Clip-Dropdown jeder einzelnen Zelle (das wählt
  stattdessen die Variante/den Testlauf). **Hovern über ein Bild** zeigt in
  allen Zellen synchron eine Lupe (Ausschnitt aus dem unskalierten
  Vollbild) an derselben relativen Position; **Rechtsklick → „In Fenster
  öffnen"** öffnet das aktuelle Bild in einem eigenen, frei skalierbaren
  Fenster. Zeile auswählen +
  „Übernehmen" setzt Ziel/CRF/Tune dieser Zeile. Der Windows-Auto-Download
  lädt jetzt den ffmpeg-„Full"-Build (braucht installiertes 7-Zip, da der
  Full-Build nur als .7z vorliegt; ohne 7-Zip Fallback auf den
  Essentials-Build wie bisher, dann ohne VMAF). Größenschätzung ist reines
  Video (ohne Audio/Untertitel)
- Zielauflösung global (Original/576p/720p/1080p/2160p), 16:9-Regel, kein Upscaling;
  „Original" behält die Quellauflösung bei; pro Zeile per Dropdown in der
  Spalte „Ziel" überschreibbar (Standard folgt der globalen Einstellung)
- CRF global vorbelegt, pro Zeile überschreibbar
- Preset global (ultrafast…veryslow, Standard medium): Geschwindigkeit ↔
  Qualität; libx265 direkt, HW-Encoder werden sinngemäß abgebildet
- Tune global + pro Zeile (Spalte „Tune"): Standard / Film-Grain (nativer
  x265-`grain`) / Animation (anime-typische x265-Parameter) / Live-Action
  (psy-rd/aq). Voll wirksam nur bei libx265; NVENC bekommt spatial-aq,
  übrige HW-Encoder ignorieren es. HDR- und Tune-x265-Parameter werden zu
  einem `-x265-params` zusammengeführt; nur für libx265 auswählbar, sonst
  ausgegraut
- Audio-Streams pro Datei per Dropdown-Checkboxen wählbar; zeigt Quell-Bitrate
  und – je nach Audio-Modus – das Zielformat inkl. Zielbitrate an.
  Audio-Modus global umschaltbar: **Kopieren** / **→ AC3** / **→ AAC**
  (jeweils max. 5.1, bereits passender Codec wird unverändert kopiert;
  Default-Zielbitrate 192 kb/s bei ≤2 Kanälen, 384 kb/s ab 3 Kanälen).
  Pro Audiospur per Rechtsklick-Kontextmenü („Audio-Modus (pro Spur)")
  individuell überschreibbar: Modus (Global/Copy/AC3/AAC), Zielbitrate
  (96–640 kb/s in 10 Stufen, oder „Automatisch" gemäß Default), Zielkanäle
  (Mono/Stereo/5.1, oder „Automatisch" = Quelle, gedeckelt auf 5.1) sowie
  Dynamikkompression (DRC, 0–4 in HandBrake-Skala, per ffmpeg-`acompressor`-
  Filter – keine 1:1-Nachbildung von HandBrakes Algorithmus, aber gleicher
  Zweck: leise Dialoge lauter, laute Passagen gedämpft, z. B. für
  Nacht-/Leise-Wiedergabe; guter Startwert: **2.0–2.5** – spürbar, ohne
  Dynamik/Räumlichkeit stark zu zerstören. 1.0–1.5 ist dezent, ab 3.0+ wird
  es aggressiv, 4.0 komprimiert praktisch alles auf denselben Pegel).
  Ein gesetzter Kanal- oder DRC-Override erzwingt
  ein Re-Encode auch dann, wenn die Quelle bereits im Zielcodec vorliegt.
  Überschriebene Spuren zeigen `[override]` im Dropdown-Label, aktive DRC
  zusätzlich `DRC <Stufe>`.
  Atmos-/DTS:X-Objektebenen gehen beim Transcodieren verloren – die Zeile
  wird dann mit einer Warnung im Status markiert
- Untertitel und Anhänge/Datenspuren werden immer unverändert kopiert,
  unabhängig vom Video-Modus (Encode oder Copy, siehe unten)
- Encoder-Dropdown: libx265 + automatisch erkannte HW-Encoder
  (Probe-Encode beim Start), zusätzlich ein **Copy**-Eintrag als letztes
  Element – damit wird der Video-Stream unverändert durchgereicht
  (`-c:v copy`, kein Re-Encode; DV/HDR-Pipeline und Preset/Tune/Ziel
  werden übersprungen und ausgegraut). Standard bleibt **Software
  (libx265)**. Pro Zeile überschreibbar per Kontextmenü
  („Video-Modus": Global/Encode/Copy) – praktisch, wenn ein
  Qualitäts-Vergleich zeigt, dass sich ein Re-Encode für eine
  bestimmte Datei nicht lohnt
- HEVC-Profil (Main/Main 10) und Level werden nicht manuell gesetzt,
  sondern vom Encoder automatisch aus dem gewählten Pixelformat
  (8-Bit vs. 10-Bit, siehe Bittiefe/HDR-Erkennung) bzw. aus
  Auflösung/Framerate/Bitrate abgeleitet
- DV: RPU extrahieren (P7→8.1), HDR10-Encode, RPU injizieren, Mux
- Queue wächst dynamisch: Dateien während des Encodens hinzufügbar
- Queue-Verwaltung: Checkbox-Spalte schließt Dateien zeitweise vom Transcode
  aus, Kontextmenü „Nach oben/unten" ändert die Reihenfolge, „Aus Liste
  entfernen" löscht den Eintrag – alles auch für bereits eingereihte Jobs
  (laufende Jobs sind gesperrt)
- Ausgabe: Quellordner + `.<ziel>.x265.mkv` (Teile per Punkt getrennt), global
  überschreibbar, pro Zeile editierbar; existierende Ziele werden markiert,
  nicht überschrieben
- Zeitanzeige unten: Job-/Batch-Restzeit sowie aktuelle Encoding-Geschwindigkeit
  in fps
- Log-Feld (Checkbox „Log" unten links): zeigt Aufrufe und Ausgaben von
  ffmpeg, dovi_tool und mkvmerge sowie Cropdetect-Ergebnisse
- Mehrsprachig (DE/EN), umschaltbar per Button unten links; Auswahl wird
  gespeichert

## Tests
    pip install -r requirements-dev.txt
    pytest
Unit-Tests für reine Logik (Crop-Erkennungs-Parsing, Output-Pfad-Benennung,
ffmpeg-Kommandoaufbau, Audio-Modus-Auswahl, Media-Info-Aggregation,
sysinfo-Regexe) — kein ffmpeg/GUI nötig, laufen in deutlich unter einer
Sekunde.

## Windows-Schnellstart
- **setup_and_run.bat** – legt einmalig `.venv` an, installiert PySide6, startet die App (ohne Konsole). Voraussetzung: Python 3.11+ von python.org.
- **build_exe.bat** – baut mit PyInstaller eine eigenständige `dist\HandPack-<version>.exe`
  (Version aus `version.py`), inkl. App-Icon (`icon.svg` → `icon.ico` via `make_icon.py`).
  Räumt den `build/`-Zwischenordner danach automatisch auf.

## Persistente Einstellungen
Gespeichert über `QSettings` unter Organisation „Kristian", App „HandPack":
- Windows: `HKCU\Software\Kristian\HandPack`
- Linux: `~/.config/Kristian/HandPack.conf`
- macOS: `~/Library/Preferences/com.Kristian.HandPack.plist`

## Tool-Download in der App
Fehlen ffmpeg/ffprobe, dovi_tool oder mkvmerge, erscheint unten der Button
**„Fehlende Tools herunterladen"**. Die Binaries landen im Ordner `.tools/`
neben der App (bzw. EXE) – keine Adminrechte nötig; der Punkt-Präfix hält
Sync-Clients (Nextcloud/OpenCloud) fern. Ein älterer `tools/`-Ordner wird
beim Start automatisch umbenannt. Sind alle Tools da, wird daraus
**„Tool-Updates suchen"**: vergleicht die Versionen der in `.tools/`
liegenden Binaries mit den Download-Quellen und lädt Veraltetes nach
Rückfrage neu (per PATH installierte Tools werden nicht angefasst). Quellen:
gyan.dev (Win-ffmpeg), johnvansickle.com (Linux), evermeet.cx (macOS),
GitHub-Releases von quietvoid/dovi_tool, mkvtoolnix.download (mkvmerge).

mkvmerge-Auto-Download gibt es nur unter Windows und nur, wenn **7-Zip**
installiert ist (das portable MKVToolNix-Archiv ist BCJ2-gepacktes 7z, das
weder Python noch Windows-Bordmittel entpacken können). Ohne 7-Zip bzw.
unter Linux/macOS MKVToolNix manuell installieren:
<https://mkvtoolnix.download/downloads.html>
(Linux: `apt install mkvtoolnix`, macOS: `brew install mkvtoolnix`).

---

## Docker-Deployment (Server, z. B. Unraid)

Die App läuft headless im Container und wird über **noVNC im Browser**
bedient (kein X-Server auf dem Client nötig, kein SSH-Forwarding).

### Enthaltene Tools im Image
Alle vier Tools sind bereits im Image enthalten – kein manueller Download
in der App nötig:

| Tool | Quelle im Image |
|---|---|
| ffmpeg / ffprobe | Statischer [BtbN](https://github.com/BtbN/FFmpeg-Builds)-GPL-Build (VAAPI + NVENC + libvmaf, für den VMAF-Qualitäts-Vergleich nötig — Debians eigenes `ffmpeg`-Paket hat libvmaf nicht garantiert aktiviert) |
| dovi_tool | zur Build-Zeit vom neuesten GitHub-Release geladen |
| mkvmerge | Debian-Paket `mkvtoolnix` |

Beim Öffnen von `http://server-ip:6080/` leitet eine generierte `index.html`
automatisch auf `vnc.html?autoconnect=true&resize=scale` weiter – keine
manuelle URL, kein Connect-Klick, automatische Skalierung. Das App-Fenster
wird beim Start automatisch maximiert (`HANDPACK_MAXIMIZE=1`, siehe
`docker/supervisord.conf`) und füllt damit die per `RESOLUTION` gesetzte
virtuelle Auflösung.

### Build (lokal, nur bauen)
    build_docker.bat [namespace]
baut das Image lokal und taggt es mit Name/Version aus `version.py`
(z. B. `handpack:0.1` + `handpack:latest`). Optionaler Namespace:

    build_docker.bat kristian
    → Image: kristian/handpack:0.1

### Deploy (zu einer Registry pushen)
    deploy_docker.bat <registry-host:port> [namespace]
taggt das zuvor lokal gebaute Image für die Ziel-Registry um und pusht
Version- + `latest`-Tag. Ohne Argument fragt das Skript die Registry-
Adresse interaktiv ab. **Wichtig: Host UND Port angeben** (z. B.
`192.168.178.222:5000`) – ohne Port versucht Docker HTTPS auf 443 und
schlägt mit „connection refused" fehl.

Beispiel:
    build_docker.bat kristian
    deploy_docker.bat 192.168.178.222:5000 kristian

**Voraussetzung bei einer HTTP-Registry ohne TLS** (Standard bei einer
selbstgehosteten lokalen Registry): auf der Build-Maschine in Docker
Desktop → Settings → Docker Engine das JSON ergänzen:
```json
{ "insecure-registries": ["192.168.178.222:5000"] }
```
→ Apply & Restart.

### Eigene Registry hosten (optional)
`docker-compose.registry.yml` – Stack für Dockge, startet eine private
Docker-Registry (`registry:2`) auf Port 5000. Optionaler Basic-Auth-Block
ist auskommentiert enthalten. Nur im eigenen LAN einsetzen (kein TLS).

### Start (lokal per Compose, mit lokalem Build)
    docker compose up -d
Danach im Browser: **http://server-ip:6080/**

`docker-compose.yml` bringt schon vorbereitete, teils auskommentierte
Optionen mit:
- **`RESOLUTION`** – virtuelle Bildschirmgröße (z. B. `1920x1080`)
- **`./input` / `./output`** Volumes – zusätzliche Mount-Beispiele für
  Unraid-Freigaben (`/mnt/user/...`) sind als Kommentare vorhanden
- **`./config:/root/.config/Kristian`** – speichert die App-Einstellungen
  (Zielauflösung, CRF, Encoder, Audio-/Video-Modus, Sprache, Tool-Pfade, …)
  dauerhaft über Container-Neuerstellung/Image-Updates hinweg. Ohne dieses
  Volume werden die Einstellungen bei jedem Rebuild/Update auf die
  Standardwerte zurückgesetzt. Der Container läuft als root, `QSettings`
  schreibt daher nach `/root/.config`.
- **Dateiberechtigungen**: Da der Container als root läuft, schreiben
  ffmpeg/dovi_tool/mkvmerge Ausgabedateien mit root als Eigentümer. Für
  den App-Prozess ist `umask 000` gesetzt (`docker/supervisord.conf`),
  neue Dateien/Ordner landen also als `666`/`777` (les-/schreibbar für
  alle) statt standardmäßig `644` — sonst könnte ein Nicht-root-User beim
  Zugriff auf `./output` die Ergebnisse nur lesen, nicht überschreiben/
  löschen. Vor dieser Änderung geschriebene Dateien brauchen einmalig
  `chmod -R a+rw ./output`.
- **GPU-Passthrough** (siehe unten)

### Deployment über Dockge
`build: .` im Compose funktioniert nur, wenn Dockge Zugriff auf den
Quellcode hat. Einfacher: Image bauen + zur Registry pushen
(`build_docker.bat` + `deploy_docker.bat`, siehe oben) und in Dockge
`docker-compose.dockge.yml` als Stack einfügen – die nutzt bereits
`image: <registry>/handpack:<tag>` statt `build: .`, kein Quellcode auf
dem Server nötig. `<REGISTRY>`/`<TAG>` bzw. die Beispielwerte im File an
die eigene Registry-Adresse anpassen.

### GPU-Passthrough (Unraid)
In `docker-compose.yml` auskommentiert vorbereitet für:
- **NVIDIA** – braucht `nvidia-container-toolkit` auf dem Unraid-Host;
  GPU-UUID ermitteln mit `nvidia-smi -L`, per `device_ids` anpinnen
  (auch MIG-Instanzen unterstützt)
- **AMD / Intel** – Passthrough einzelner `/dev/dri/renderDXXX`-Nodes;
  Auflisten mit `ls -la /dev/dri/`
- **Intel SR-IOV** – Virtual Functions einzeln zuweisbar (VF ≠ physische GPU)

Passender ffmpeg-Encoder muss zusätzlich in der App ausgewählt werden:
`hevc_nvenc` (NVIDIA), `hevc_amf` (AMD), `hevc_qsv` (Intel/VAAPI).
Kernel-Treiber selbst kommen immer vom Host – ein Container kann sie nicht
mitbringen, da der Kernel geteilt wird; das Image liefert nur die
passenden Userspace-Bibliotheken (VAAPI-Treiber für AMD/Intel).

Multi-GPU: `device_ids` (NVIDIA) bzw. konkrete `renderD1xx`-Nodes
(AMD/Intel) statt "alle GPUs" verwenden, um eine bestimmte Karte pro
Container anzupinnen.
