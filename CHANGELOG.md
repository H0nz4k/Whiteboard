# Changelog – Whiteboard Monitor

Všechny významné změny projektu.

## [1.3.9] – 2026-02-26

### Agent – Detekce změn a Web UI

- **Změna pixelů a diff** – porovnání last_saved vs current (správně), ne předchozí live vs current. Diff a „Změna pixelů“ ukazují změnu od posledního eventu.
- **Tlačítko Make last** – vedle Live uloží aktuální náhled jako referenční snímek (last_saved.jpg). Použij když jsou smazané last soubory.
- **Rozdíl jasu před/po** – používá last_saved pro výpočet, zobrazuje hodnotu i zeleně (není jen šedě). Vysvětlení v roletě „Co znamená blokace eventu?“.
- **7. bod analýzy** – Vytvoření eventu (zeleně/červeně/šedě podle stavu).
- **Písmo** – zvětšeno napříč celým UI (nastavení, analýza, náhledy).

## [1.3.8] – 2026-02-26

### Agent – Web UI opravy a vylepšení

- **Aktuální jas** – živé zobrazení u pole Min. osvětlení a pod live náhledem (např. „Aktuální jas: 85 / min. 100“)
- **Min. osvětlení default 100** – výchozí hodnota v config.example.yaml
- **Uložení nastavení** – zpráva „Uloženo“ po uložení, zobrazení chyb při selhání
- **Debug** – config_path, config_ok v sekci ověření kamery
- **Opravy syntaxe JS** – uvozovky v item(), escape \\n v join(), odstranění ?? a ?. pro kompatibilitu
- **Chyby při načítání configu** – zobrazení chybové hlášky místo tichého selhání

## [1.3.7] – 2026-02-26

### Agent – Web UI analýza

- **Analýza v bodech** – podmínky splněno (✓) / nesplněno (✗) pro uložení eventu: Aktuální osvětlení, Limitní osvětlení, Změna pixelů, Hitů, Cooldown, Ustálení, Rozdíl jasu
- **Aktuální a limitní osvětlení** – vždy zobrazeny na začátku analýzy (i bez dat)
- **Analýza bez dat** – struktura se zobrazuje i když kamera neběží (placeholdery, nápověda k restartu)
- **Hub Live** – odkaz „Nastavení + analýza na RPi“ pro přechod na plné nastavení agenta

## [1.3.6] – 2026-02-26

### Agent – Web UI nastavení

- **Defaultní hodnoty** – všechna pole formuláře mají předvyplněné výchozí hodnoty (CLAHE 2, JPEG 90, práh 0.35, interval 3 s, ROI 150/80/1300/900 atd.)
- **Live – datum a čas** – živé zobrazení aktuálního data a času nad náhledem kamery, datum a čas snímku pod obrázkem
- **Layout preview** – pořadí: Live → Last (poslední uložená změna) → Diff (nová změna oproti live) → Analýza
- **Analýza** – nadpis „Co musí být splněno, aby se diff stal eventem“ – přehled podmínek pro živé ladění

## [1.3.5] – 2026-02-26

### Agent – Live kamera (picamera2, Debian Trixie)

- **picamera2 backend** – výchozí pro CSI kameru, nepotřebuje libcamera-v4l2
- **PYTHONPATH** v whiteboard-agent.service – `/usr/lib/python3/dist-packages` pro přístup k `python3-libcamera`
- **requirements.txt** – přidán `picamera2>=0.3.12`
- **libcamera-v4l2** – služba volitelná; install-agent.sh ji neinstaluje, pokud binárka neexistuje (Debian Trixie)
- **Debug endpoint** `/api/debug` – `stream_updated_ago`, `last_jpg_age`, `stream_active`, `hint` pro ověření stavu kamery
- **TROUBLESHOOT** – picamera2 ModuleNotFoundError, libcamera-v4l2 chybějící binárka, whiteboard-live, CRLF u skriptů

### Agent – soubory pro deploy

- **agent/** – kompletní sada pro RPi: main.py, webapp.py, config.example.yaml, requirements.txt, check_camera.py, cleanup_agent.sh, ensure_config.py, fix_config.sh, whiteboard-agent.service, libcamera-v4l2.service, install-agent.sh

---

## [1.3.4] – 2026-02-26

### Hub – Nastavení a SMS notifikace

- **Stránka Nastavení** (`/settings`) – tlačítko v hlavičce, bloky SMS notifikace a Mail (placeholder)
- **SMS notifikace** – zapnout/vypnout, čísla, text zprávy, časové okno (od–do), denní limit, trigger (každá změna / první za den), počítadlo + reset
- **`{datetime}`** v textu SMS – automaticky datum a čas změny ve formátu dd.mm.rrrr hh:mm
- **Tlačítko Odeslat test** – testovací SMS po uložení nastavení
- **Config** – ukládání do `config.yaml` vedle app.py (fallback na `/opt/whiteboard-hub/` při absenci env)
- **Config** – při prvním startu se automaticky zkopíruje `config.example.yaml` → `config.yaml`, pokud config neexistuje
- **UI** – nadpis „SMS notifikace“, větší checkbox pro povolení odesílání

## [1.3.3] – 2026-02-26

### Agent – filtrování změn jen v osvětlení

- **`max_brightness_change_percent`** (default 35) – při větším relativním rozdílu jasu mezi snímkem před a po se event neposílá (považuje se za změnu jen osvětlení)
- **`pixel_threshold`** (default 30) – práh rozdílu pixelů pro detekci změny; vyšší hodnota = méně citlivé na drobné změny osvětlení
- **Robustnější normalizace jasu** – při extrémním rozdílu (scale mimo 0.7–1.4) se používá aditivní místo multiplikativní normalizace (zabraňuje saturaci)
- **Blokace „rozdíl jasu (jen osvětlení)“** – zobrazení v UI, když se event neposílá kvůli velkému rozdílu osvětlení

## [1.3.2] – 2026-02-25

### Dokumentace a UI

- **README** – nová sekce „Co znamená Blokuje event“ s tabulkou hitů 0/2, 1/2, 2/2 a vysvětlením ustálení a cooldownu
- **Web UI** – roleta „Co znamená blokace eventu?“ pod live náhledem s vysvětlivkami

## [1.3.1] – 2026-02-25

### Agent

#### Osvětlení nezávislá detekce
- **`illumination_invariant`** (default true) – před porovnáním snímků se normalizuje jas aktuálního snímku na referenční
- Výrazně méně falešných detekcí při stmívání a rozednívání (změny osvětlení už nejsou považovány za změnu obsahu)
- Nastavení v Web UI: Detekce změn → „Osvětlení nezávislá detekce“

## [1.3.0] – 2026-02-24

### Hub

#### Stránka last_event (Historie)
- **`/last_event`** – nová stránka s historií eventů
- Každý event: snímek před změnou + datum, snímek po změně + datum
- Responzivní pro mobil i PC (safe-area, grid 1 sloupec na mobilu)
- Odkaz na detail (`/last_diff?e=...`)

#### Úpravy indexu
- Tlačítko **Historie** vedle Poslední změna a Live kamera
- Roleta s historií odstraněna – historie přes tlačítko na `/last_event`
- Polling každých **10 s** (místo 2 s) – reload jen při novém eventu

#### last_diff
- Fallback: když chybí frame_before, použije se předchozí event
- Diff sekce odstraněna – jen před/po
- Responzivní pro mobil

#### SMS
- Logování při selhání (base_url, numbers, send.sh, exit code)
- Logování při úspěchu

### Agent

#### Rychlý režim pro jasné změny
- **`fast_change_threshold_percent`** (default 1.5) – při změně ≥ tento % přeskoč ustálení, odešli hned
- Nižší hodnota = rychlejší reakce na zřetelné změny

#### Diagnostika
- **`block_reason`** v status.json – proč se event neodešle: `hitů 2/4`, `ustálení 3/6`, `cooldown 12s`
- Zobrazení v Web UI pod live náhledem (žlutě)
- Pole **Rychlý práh** v nastavení detekce

#### Logování
- Při selhání odeslání na hub: `[cam] Hub nedostupný: …` nebo `[cam] Hub odmítl: 401 …`

## [1.2.0] – 2026-02-24

### Přidáno

#### Stránka last_diff
- **`/last_diff`** – samostatná stránka s poslední změnou: snímek před změnou, po změně, diff a čas změny
- **`/last_diff?e=<rel>`** – odkaz na konkrétní event (rel = events/device/datum/cas)
- Tlačítko „Poslední změna“ v hlavičce přehledu
- V historii u každého eventu odkaz „Odkaz“ na danou změnu

#### SMS notifikace při změně
- **Config `sms`** – `base_url`, `message`, `numbers`
- Při každém novém eventu (POST `/api/whiteboard/event`) hub odešle SMS na všechna čísla s odkazem na `last_diff`
- Vyžaduje `/opt/sms/send.sh` na serveru (projekt sms – Huawei E3372h, Gammu)
- Pokud `base_url` nebo `numbers` chybí, SMS se neodesílají

### Config – nové klíče (hub)

```yaml
sms:
  base_url: "https://vase-domena.cz"
  message: "Změna na tabuli: {url}"
  numbers:
    - "+420731164187"
```

## [1.1.0] – 2026-02-18

### Přidáno

#### Min. osvětlení
- **`processing.min_brightness`** (0–255, `null` = vypnuto) – při průměrném jasu v ROI pod touto hodnotou se nic neukládá ani neposílá (last.jpg, last_diff.png, last_ocr.txt, eventy)
- Slouží k tomu, aby se při zhasnutém světle v kuchyni neposílaly zbytečné snímky
- **Aktuální jas** – živé zobrazení v Web UI u pole Min. osvětlení a pod live náhledem (např. „Aktuální jas: 85 / min. 40“)
- Jas se měří jako průměr pixelů v ROI (0 = černá, 255 = bílá)

#### Ustálení obrazu
- **`processing.stabilization_enabled`** (true/false) – čekat na ustálení před odesláním eventu
- **`processing.stabilization_frames`** (2–10) – kolik snímků bez změny před odesláním
- **Průběh:** 1) Detekce změny (consecutive hits) → 2) čekání na N stabilních snímků → 3) porovnání s referenčním snímkem (před změnou) → 4) pokud je obraz stále jiný = skutečná změna na tabuli → odešle event; pokud podobný = průchod osoby → ignoruje
- **Průchod osob** – osoba projde před kamerou a odejde; obraz se vrátí k původnímu stavu → porovnání s referencí vyhodnotí jako „žádná změna“ → event se neodešle
- **Psaní na tabuli** – během psaní se obraz mění průběžně; až po dopsání se ustálí → event se odešle až po dokončení

#### API a status
- **`/api/status`** – vrací status.json (brightness, state, stabilization, hits)
- Status zobrazuje stav „čeká na ustálení (2/3)“ při aktivní stabilizaci

#### OCR vylepšení (z předchozích iterací)
- **`ocr.preprocess`** – otsu | adaptive | none (pro ruční písmo zkus none)
- **`ocr.min_side`** – min. rozměr obrázku pro OCR (automatické zvětšení malého ROI)
- **`ocr.debug_save_input`** – ukládá last_ocr_input.png pro kontrolu ROI

### Config – nové klíče (processing)

```yaml
processing:
  roi: {x: 550, y: 160, w: 1250, h: 600}
  min_brightness: 40        # null = vypnuto
  stabilization_enabled: true
  stabilization_frames: 3
```

**Poznámka:** `roi` musí být na jednom řádku jako objekt `{x, y, w, h}`. Při ruční úpravě nebo sed dej pozor, aby se struktura neporušila.

## [1.0.0] – 2026-02-18

### Přidáno

- **Agent (RPi3)**
  - Zachytávání z CSI kamery (picamera2) nebo USB (OpenCV)
  - Automatický fallback: picamera2 → OpenCV při selhání
  - Detekce změn na tabuli (práh, consecutive hits, cooldown)
  - OCR (Tesseract) – čeština, angličtina
  - Web UI na portu 8081 – nastavení kamery, OCR, ROI, live náhled
  - Ukládání: last.jpg, last_diff.png, last_ocr.txt
  - Odesílání eventů na HUB při detekované změně
  - Vše v `/opt/whiteboard-agent/` (config, data)

- **Hub (server)**
  - Přijímání eventů od agenta
  - Proxy pro live náhled z RPi
  - UI pro zobrazení eventů a live streamu

- **Deploy**
  - `deploy.sh` – Bash, rsync + SSH (Linux/Git Bash)
  - `deploy-agent.ps1` – PowerShell pro Windows
  - `install.sh` – na zařízení: kopírování z /tmp do /opt, restart služby
  - Automatické vytvoření config.yaml z config.example.yaml při prvním deployi

- **Diagnostika**
  - `check_camera.py` – kontrola /dev/video*, OpenCV, libcamera
  - `fix_config.sh` – diagnostika configu na RPi
  - `ensure_config.py` – doplnění live_server do configu

- **Dokumentace**
  - README.md – instalace, konfigurace, deploy
  - TROUBLESHOOT.md – řešení problémů

### Technické detaily

- **Agent venv**: `--system-site-packages` pro přístup k libcamera (python3-picamera2)
- **Kamery**: picamera2 (CSI), OpenCV (USB/V4L2)
- **Rozlišení**: 1920×1080 doporučeno pro RPi CSI
