<p align="center">
  <img src="logo.png" width="160" alt="BRUdirekt Logo"/>
</p>

# BRUdirekt — Home Assistant Integration für das Brunata-Nutzerportal München

Custom Integration für Home Assistant, die Heizungs- und Warmwasserverbrauchsdaten aus dem
[Brunata-Nutzerportal München](https://nutzerportal.brunata-muenchen.de) (SAP OData-Backend)
holt und als Sensoren anzeigt — inklusive Zählerstände, Abrechnungsvorjahr-Vergleich,
Jahresprognose und Raumaufschlüsselung.

## Funktionen

- Login mit E-Mail/Passwort über das Portal (SAP-`$batch`-Flow) — keine API-Keys nötig
- Sensoren pro verfügbarem Kostentyp (`HZ…` = Heizung, `WW…` = Warmwasser):
  - **YTD-Verbrauch** (kumuliert, `device_class: energy`/`volume` → nutzbar in Dashboards/Energy-UI)
  - **Letzter Monat** (inkl. Attribut `months` mit der kompletten Monatsreihe)
  - **Zählerstand** (kumuliert)
  - **Vergleich** (Gebäude-/Bundesdurchschnitt in kWh/m²)
  - **Prognose** (Jahresprognose + Vorjahr)
  - **Raumverbräuche** (ein Sensor pro Raum, inkl. Anteil in %)
- Auth-Fehler werden sauber als Re-Auth erkannt; temporäre Fehler führen zu automatischen
  Retry-Versuchen (`ConfigEntryNotReady`)
- Update-Intervall pro Eintrag einstellbar (Options-Flow, Standard: 6 h)

## Voraussetzungen

- Ein BRUdirekt-/Nutzerportal-Konto (München) mit E-Mail + Passwort
- Home Assistant (Custom Integration)

## Installation

### HACS (empfohlen)

1. HACS: *Erweitert → Andere Repositories hinzufügen* →
   `https://github.com/klaffka/brunata-nutzerportal` (Kategorie: *Integration*).
2. Integration **BRUdirekt (Brunata München)** installieren und HA neu starten.
3. Integration einrichten (siehe unten).

### Manuell (ohne HACS)

1. Den Ordner `brunata_nutzerportal` aus `custom_components/` nach
   `config/custom_components/` kopieren.
2. Home Assistant neu starten.

### Integration einrichten

Unter *Einstellungen → Geräte & Dienste → Integrationen hinzufügen* **BRUdirekt (Brunata München)**
auswählen und mit E-Mail/Passwort anmelden (Portal-URL und SAP-Client `201` sind vorbefüllt).
Das Backend-Paket `brunata-nutzerportal-api` wird dabei automatisch installiert.

### Test-Setup (Docker, dieses Repo)

```bash
docker compose -f test/docker-compose.yaml up -d
```

Home Assistant läuft dann auf http://localhost:8123 mit der Konfiguration aus `test/ha-config/`
(die Integration wird aus `custom_components/` gemountet). Logs:
`test/ha-config/home-assistant.log` (Debug-Logging für `brunata_nutzerportal` + `brunata_api` ist aktiv).

> Hinweis: Port 8123 kann mit anderen lokalen HA-Instanzen kollidieren — dann in
> `test/docker-compose.yaml` den Host-Port ändern.

## Optionen

Über *Integration → Rädchen → Einstellungen* lässt sich das
**Aktualisierungsintervall** in Stunden setzen (1–168, Standard 6). Das Portal aktualisiert
Abrechnungsdaten meist wöchentlich; kürzere Intervalle erhöhen den Aufwand auf dem Portal.

## Projektstruktur (Entwicklung)

```
custom_components/brunata_nutzerportal/   ← die Integration (HACS-Layout, Single Source of Truth)
hacs.json                                 HACS-Metadaten
main.py                                   Standalone-Login-Skript (SAP-$batch-Flow) gegen das echte Portal
requirements.txt                          Abhängigkeiten für main.py (venv/)
notes                                     curl-Aufzeichnungen des Portal-Login-Flows (Referenz, git-ignoriert)
test/docker-compose.yaml                  HA-Testcontainer (mountet custom_components/ nach /config)
test/ha-config/                           HA-Test-Config (Runtime-State ist git-ignoriert)
test/test_coordinator_logic.py            Logik-Tests ohne HA:  venv/bin/python test/test_coordinator_logic.py
logo.png                                  Logo (Flamme + Wassertropfen)
```

Die Integration nutzt das PyPI-Paket [`brunata-nutzerportal-api`](https://pypi.org/project/brunata-nutzerportal-api/)
(fixiert in `manifest.json`). Dieses liegt **nicht** in diesem Repo — bei API-Problemen dort
nachschauen bzw. im venv installieren (`pip install brunata-nutzerportal-api`) und mit einem
Probe-Skript gegen das Portal testen (Login → `get_supported_cost_types` →
`get_current_consumption` → `get_readings` → …).

**Änderungen an der Integration** erfordern einen Neustart des Containers:
`docker restart homeassistant` (HA-Reload reicht für Custom Components nicht).

## Fehlerbehebung

- **Re-Auth-Dialog**: Portal-Login fehlgeschlagen (Falsches Passwort, Sperrung, Portal-Änderung).
  Zugangsdaten neu eingeben.
- **Entry bleibt „not ready"**: Netzwerk/Portal vorübergehend nicht erreichbar — HA retryt
  automatisch.
- **Sensor fehlt**: Der zugehörige Kostentyp ist für das Konto nicht im Dashboard hinterlegt
  (z. B. kein `WW`-Zähler → keine Warmwasser-Sensoren).
- Details: `home-assistant.log` (debug) bzw. `docker logs homeassistant`.

## Hinweise

- Alle Daten bleiben im eigenen HA-Setup; es werden nur die normalen Portal-Endpunkte
  aufgerufen, die auch die Browser-Oberfläche nutzt.
- `.env` und `notes` enthalten echte Zugangsdaten — nicht committen/teilen.