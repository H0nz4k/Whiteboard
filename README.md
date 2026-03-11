# Whiteboard Camera System 📸

Kompletní systém pro sledování, digitalizaci a archivaci obsahu fyzické tabule (whiteboardu). Systém se skládá ze dvou částí: **Agenta** (kamera) a **Hubu** (server/archiv).

## 🏗️ Architektura

Systém funguje na principu klient-server:

1.  **Agent (Kamera):**
    *   Běží typicky na **Raspberry Pi** přímo u tabule.
    *   Inteligentně detekuje změny (psaní/mazání) a ignoruje změny osvětlení.
    *   Provádí OCR (rozpoznání textu).
    *   Odesílá snímky na Hub.
    *   Má vlastní Web UI pro nastavení (ROI, citlivost).

2.  **Hub (Server):**
    *   Běží na domácím serveru, NASu nebo cloudu.
    *   Přijímá data od Agenta.
    *   Ukládá historii změn (časová osa).
    *   **Posílá notifikace:** SMS / Upozornění při detekci nové zprávy na tabuli.
    *   Zobrazuje webové rozhraní s historií.

---

## 📸 Část 1: Agent (Kamera)

Složka: `whiteboard/agent/`

Agent je "oko" systému. Používá pokročilé algoritmy (Adaptive Thresholding + Contours), aby rozeznal skutečné psaní fixou od stínů nebo změny slunečního svitu.

### Instalace (na Raspberry Pi)

1.  Připojte kameru (RPi Camera Module nebo USB webkameru).
2.  Jděte do složky agenta a spusťte instalaci:
    ```bash
    cd whiteboard/agent
    chmod +x install-agent.sh
    ./install-agent.sh
    ```
3.  Zkontrolujte, zda služba běží:
    ```bash
    systemctl status whiteboard-agent
    ```

### Konfigurace Agenta
Agent má webové rozhraní na portu **8081**.
*   Otevřete v prohlížeči: `http://<IP-RPI>:8081`
*   Zde nastavte **ROI** (výřez tabule) a **Citlivost detekce**.
*   Fyzická konfigurace je v `/opt/whiteboard-agent/config.yaml`.

---

## 🧠 Část 2: Hub (Server)

Složka: `whiteboard/hub/`

Hub slouží jako centrální úložiště a brána pro notifikace.

### Instalace (Server/PC)

1.  Jděte do složky hubu:
    ```bash
    cd whiteboard/hub
    ```
2.  Vytvořte virtuální prostředí a nainstalujte závislosti:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```
3.  Nastavte konfiguraci:
    ```bash
    cp config.example.yaml config.yaml
    nano config.yaml
    ```
    *Zde nastavte cestu pro ukládání obrázků a údaje pro SMS bránu.*

4.  Spusťte aplikaci (nebo vytvořte systemd službu):
    ```bash
    python3 app.py
    ```

### Funkce Hubu
*   **API Endpoint:** Naslouchá na `/api/whiteboard/event` pro data z agenta.
*   **Web UI:** Zobrazuje aktuální stav tabule a historii změn.
*   **Notifikace:** Pokud přijde validní změna, Hub může odeslat SMS nebo jinou notifikaci (dle nastavení v `config.yaml`).

---

## 🚀 Jak to funguje dohromady

1.  Někdo napíše vzkaz na tabuli.
2.  **Agent** detekuje změnu, počká na ustálení obrazu (aby nefotil osobu před tabulí) a provede OCR.
3.  **Agent** odešle fotku + text na **Hub**.
4.  **Hub** uloží fotku do historie.
5.  **Hub** vyhodnotí, zda poslat SMS (např. "Nový vzkaz na tabuli: Koupit mléko").
6.  Uživatel se může podívat na web Hubu, co je na tabuli, aniž by tam musel chodit.

## 📂 Struktura repozitáře

*   `whiteboard/agent/` - Kód pro Raspberry Pi (kamera, detekce).
*   `whiteboard/hub/` - Kód pro Server (web, historie, SMS).
*   `whiteboard/services/` - Systemd unity pro automatické spouštění.
