# Whiteboard Agent 📸

Inteligentní kamerový agent pro digitalizaci fyzických tabulí (whiteboardů). Běží na Raspberry Pi (nebo jiném Linuxu), sleduje tabuli a při detekci psaní/mazání odešle snímek na centrální Hub.

## ✨ Klíčové vlastnosti

*   **Adaptivní detekce změn:** Díky pokročilému zpracování obrazu (Adaptive Thresholding + Contours) ignoruje změny osvětlení (stíny, rozednívání, mraky) a reaguje pouze na skutečné tahy fixou.
*   **Webové rozhraní:** Okamžitý náhled kamery, ladění detekce a kompletní konfigurace přes prohlížeč (port `8081`).
*   **OCR:** Integrovaná podpora Tesseract OCR pro převod textu z tabule na digitální text.
*   **Odolnost:** Běží jako systémová služba. Při výpadku sítě ukládá události do fronty a odešle je po obnovení spojení.
*   **Podpora kamer:** Funguje s Raspberry Pi kamerami (`libcamera`/`picamera2`) i běžnými USB webkamerami (`OpenCV`).

## 🚀 Instalace

Agent je navržen primárně pro **Raspberry Pi** s OS Debian/Raspbian (Bookworm/Bullseye).

1.  **Klonování repozitáře:**
    ```bash
    git clone <url-repozitare>
    cd whiteboard/agent
    ```

2.  **Spuštění instalace:**
    Skript vytvoří virtuální prostředí (venv), nainstaluje závislosti (OpenCV, Flask...) a nastaví systemd služby.
    ```bash
    chmod +x install-agent.sh
    ./install-agent.sh
    ```

3.  **Kontrola stavu:**
    ```bash
    systemctl status whiteboard-agent
    ```

## ⚙️ Konfigurace a Web UI

Po spuštění je agent dostupný na:
👉 **http://<IP-ADRESA-RPI>:8081**

V rozhraní můžete nastavit:
*   **ROI (Region of Interest):** Oříznutí obrazu jen na plochu tabule.
*   **Režim detekce:**
    *   *Adaptivní (Doporučeno):* Ignoruje stíny, detekuje kontury písma. Nastavuje se citlivost `C`.
    *   *Klasický:* Jednoduché porovnání pixelů (citlivé na světlo).
*   **Minimální osvětlení:** Aby kamera neodesílala černé snímky v noci.
*   **OCR:** Zapnutí/vypnutí rozpoznávání textu a jazyk (ces/eng).

Konfigurace se fyzicky ukládá do souboru `/opt/whiteboard-agent/config.yaml`.

## 🛠️ Jak to funguje (Technické detaily)

1.  **Snímání:** Kamera snímá obraz v nastaveném intervalu (default 3s).
2.  **Předzpracování:** Obraz se ořízne (ROI), převede na stupně šedi a aplikuje se CLAHE (zvýšení kontrastu).
3.  **Detekce:**
    *   Obraz se silně rozmaže (Blur) pro odstranění šumu senzoru.
    *   Provede se adaptivní prahování (Adaptive Threshold).
    *   Porovná se aktuální snímek s předchozím.
    *   Filtrují se pouze změny, které mají tvar "tahu" (Contours), aby se eliminoval drobný šum.
4.  **Stabilizace:** Pokud je detekována změna, agent čeká, až se obraz ustálí (např. až osoba odejde od tabule).
5.  **Odeslání:** Výsledný snímek + rozdílová maska se odešlou POST požadavkem na Hub.

## 📂 Struktura složek

*   `main.py`: Hlavní smyčka agenta (kamera, detekce, odesílání).
*   `webapp.py`: Flask server pro webové rozhraní.
*   `check_camera.py`: Diagnostický skript pro test kamery.
*   `install-agent.sh`: Instalační skript.

## 🐛 Řešení problémů

*   **Kamera nenabíhá:** Zkuste `python3 check_camera.py`.
*   **Falešné detekce při stmívání:** V Web UI zvyšte hodnotu `Citlivost (C)` nebo zvyšte `Min. osvětlení`.
*   **Logy:** `journalctl -u whiteboard-agent -f`
