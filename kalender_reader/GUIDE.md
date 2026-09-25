# 📅 Google Calendar Library — Vollständiger Guide

**`google_calendar.py`** ist eine vollständige Python-Bibliothek, mit der du deinen Google Kalender komplett kontrollieren kannst: Events lesen, erstellen, bearbeiten, löschen, wiederkehrende Events, Farben, Erinnerungen, Standorte, Anhang-Einladungen und vieles mehr.

> In diesem Projekt wird sie von [`calendar_sync.py`](calendar_sync.py) verwendet, um jeden
> Zeitnachweis automatisch als Kalender-Event anzulegen. Dieser Guide dokumentiert die
> Bibliothek selbst — für eigene Skripte, die `GoogleCalendar` direkt nutzen wollen.
> Zum manuellen Testen aller Funktionen siehe [`test.py`](test.py).

---

## 📋 Inhaltsverzeichnis

1. [Installation & Setup](#1-installation--setup)
2. [Datei-Struktur](#2-datei-struktur)
3. [Erster Start & Authentifizierung](#3-erster-start--authentifizierung)
4. [Grundlegende Verwendung](#4-grundlegende-verwendung)
5. [Events lesen](#5-events-lesen)
6. [Events erstellen](#6-events-erstellen)
7. [Events bearbeiten](#7-events-bearbeiten)
8. [Events löschen](#8-events-löschen)
9. [Wiederkehrende Events](#9-wiederkehrende-events)
10. [Duplikate verwalten](#10-duplikate-verwalten)
11. [Kalender-Verwaltung](#11-kalender-verwaltung)
12. [Farben-Referenz](#12-farben-referenz)
13. [Erinnerungen-Referenz](#13-erinnerungen-referenz)
14. [Vollständiges Beispiel](#14-vollständiges-beispiel)
15. [Batch-Requests](#15-batch-requests-viele-änderungen-auf-einmal)
16. [Fehlerbehebung](#16-fehlerbehebung)

---

## 1. Installation & Setup

### Schritt 1 — Python-Pakete installieren

```bash
pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
```

### Schritt 2 — Google Cloud Console einrichten

1. Öffne **https://console.cloud.google.com/**
2. Erstelle ein neues Projekt (oder wähle ein vorhandenes)
3. Gehe zu **APIs & Services → Library**
4. Suche `Google Calendar API` und klicke **Enable**
5. Gehe zu **APIs & Services → Credentials**
6. Klicke **+ CREATE CREDENTIALS → OAuth 2.0 Client ID**
7. Wähle **Desktop application** als Application type
8. Klicke **Create**, dann auf den **Download-Button** (JSON-Icon)
9. Benenne die Datei um zu **`credentials.json`**

---

## 2. Datei-Struktur

```
kalender_reader/
│
├── google_calendar.py       ← die Bibliothek (diese Datei nicht bearbeiten)
├── calendar_sync.py         ← nutzt die Bibliothek für den Zeitnachweis-Sync
├── credentials.json         ← von Google Cloud Console heruntergeladen (nicht in Git)
├── token.pickle             ← wird automatisch erstellt (nicht in Git)
└── test.py                  ← manuelles Test-Skript für die Bibliothek
```

`credentials.json` und `token.pickle` sind bereits über die Projekt-`.gitignore`
ausgeschlossen — nichts weiter zu tun.

> ⚠️ **Wichtig:** Committe `credentials.json` und `token.pickle` **niemals** in Git!
> Füge beide zu `.gitignore` hinzu.

**.gitignore Einträge:**
```
credentials.json
token.pickle
```

---

## 3. Erster Start & Authentifizierung

Beim **ersten** Ausführen öffnet sich automatisch ein Browser-Fenster:
- Google fragt dich, deinen Account zu autorisieren
- Klicke auf **Zulassen**
- Das Token wird als `token.pickle` gespeichert
- Bei allen weiteren Starts läuft die Authentifizierung **automatisch** im Hintergrund

```python
from google_calendar import GoogleCalendar

# Beim ersten Start → Browser öffnet sich
cal = GoogleCalendar()

# Mit eigenen Pfaden (z.B. wenn Dateien in einem Unterordner sind)
cal = GoogleCalendar(
    credentials_path='config/credentials.json',
    token_path='config/token.pickle',
)

# Andere Zeitzone (Standard ist Europe/Berlin)
cal = GoogleCalendar(timezone='America/New_York')
```

---

## 4. Grundlegende Verwendung

```python
from google_calendar import GoogleCalendar

cal = GoogleCalendar()

# Nächste 10 Events anzeigen
events = cal.get_upcoming_events(10)
cal.print_events(events)

# Kurze Übersicht
cal.print_summary(events)
```

---

## 5. Events lesen

### Nächste X Events abrufen

```python
# Nächste 5 Events
events = cal.get_upcoming_events(max_results=5)

# Von einem anderen Kalender (ID aus list_calendars())
events = cal.get_upcoming_events(max_results=10, calendar_id='work@group.calendar.google.com')
```

### Events in einem Zeitraum

```python
from datetime import date

# Alle Events im Mai 2026
events = cal.get_events_in_range(
    start=date(2026, 5, 1),
    end=date(2026, 5, 31),
)

# Mit ISO-Strings
events = cal.get_events_in_range(
    start='2026-05-01',
    end='2026-05-31T23:59:59',
)
```

### Suche nach Keyword

```python
# Alle Events die "Meeting" enthalten
results = cal.search_events("Meeting")

# In einem bestimmten Kalender
results = cal.search_events("Urlaub", max_results=20)
```

### Event nach Titel finden

```python
# Gibt das erste passende Event zurück
event = cal.get_event_by_title("Team Meeting")

if event:
    print(event['id'])        # Event-ID
    print(event['summary'])   # Titel
    print(event['start'])     # Startzeit
```

### Event nach ID laden

```python
event = cal.get_event_by_id("abc123xyz...")
```

### Events anzeigen

```python
# Detaillierte Ansicht
cal.print_events(events)

# Mit Event-IDs anzeigen (nützlich zum Debuggen)
cal.print_events(events, show_id=True)

# Kompakte Übersicht (eine Zeile pro Event)
cal.print_summary(events)
```

---

## 6. Events erstellen

### Einfaches Event

```python
cal.create_event(
    title='Team Meeting',
    start='2026-05-05T14:00:00',
    end='2026-05-05T15:00:00',
)
```

### Event mit allen Optionen

```python
cal.create_event(
    title='Zahnarzt',
    start='2026-05-10T10:00:00',
    end='2026-05-10T11:00:00',
    location='Dr. Müller, Hauptstr. 5, Berlin',
    description='Routine-Check. Versicherungskarte mitbringen.',
    color='blueberry',
    reminders=[
        {'method': 'popup', 'minutes': 30},   # 30 Min vorher
        {'method': 'email', 'minutes': 1440}, # 1 Tag vorher per E-Mail
    ],
)
```

### Event mit datetime-Objekten

```python
from datetime import datetime, timedelta

start = datetime(2026, 5, 15, 9, 0, 0)   # 15.05.2026 um 09:00
end   = start + timedelta(hours=2)        # 2 Stunden später

cal.create_event(
    title='Workshop',
    start=start,
    end=end,
    location='Konferenzraum B',
)
```

### Event ohne Endzeit (automatisch +1 Stunde)

```python
cal.create_event(
    title='Kurzes Meeting',
    start='2026-05-12T15:00:00',
    # end wird automatisch auf 16:00 gesetzt
)
```

### Event mit Einladungen

```python
cal.create_event(
    title='Projekt-Kickoff',
    start='2026-05-20T10:00:00',
    end='2026-05-20T11:30:00',
    attendees=[
        'anna@example.com',
        'bob@example.com',
        'chef@firma.de',
    ],
    description='Kickoff-Meeting für das neue Projekt.',
    color='tomato',
)
```

### Ganztages-Event

```python
# Einzelner Tag (z.B. Feiertag)
cal.create_all_day_event(
    title='Tag der Arbeit',
    day='2026-05-01',
    color='banana',
)

# Mehrtägig (z.B. Urlaub)
cal.create_all_day_event(
    title='Sommerurlaub',
    day='2026-07-14',
    end_day='2026-07-25',   # inklusive
    location='Mallorca, Spanien',
    description='Endlich Urlaub!',
    color='sage',
)

# Mit datetime-Objekt
from datetime import date
cal.create_all_day_event(
    title='Geburtstag',
    day=date(2026, 6, 15),
    color='flamingo',
)
```

---

## 7. Events bearbeiten

### Event per ID bearbeiten

```python
# Zuerst Event suchen
event = cal.get_event_by_title("Team Meeting")

# Dann bearbeiten — nur die gewünschten Felder übergeben
cal.update_event(
    event_id=event['id'],
    title='Team Meeting — VERSCHOBEN',
    start='2026-05-06T15:00:00',
    end='2026-05-06T16:00:00',
    color='tangerine',
    description='Verschoben auf Mittwoch wegen Konflikt.',
)
```

### Nur einzelne Felder ändern

```python
# Nur die Farbe ändern
cal.update_event(event_id=event['id'], color='tomato')

# Nur den Ort hinzufügen
cal.update_event(event_id=event['id'], location='Zoom – Link im Chat')

# Nur Erinnerungen setzen
cal.update_event(
    event_id=event['id'],
    reminders=[{'method': 'popup', 'minutes': 10}],
)

# Beschreibung löschen (leerer String)
cal.update_event(event_id=event['id'], description='')
```

### Direktes Bearbeiten per Titel (Kurzform)

```python
cal.update_event_by_title(
    'Zahnarzt',
    start='2026-05-15T11:00:00',
    color='blueberry',
    reminders=[{'method': 'popup', 'minutes': 60}],
)
```

---

## 8. Events löschen

### Per Event-ID löschen

```python
event = cal.get_event_by_title("Lunch Break")
if event:
    cal.delete_event(event['id'])
```

### Per Titel löschen (erstes passendes Event)

```python
cal.delete_event_by_title("Altes Meeting")
```

### Alle Events mit einem Titel löschen

```python
# Nützlich um versehentlich erstellte Duplikate zu löschen
deleted = cal.delete_all_by_title("Test")
print(f"{deleted} Events gelöscht.")
```

---

## 9. Wiederkehrende Events

### Täglich wiederholen

```python
cal.create_recurring_event(
    title='Mittagspause',
    start='2026-05-04T12:00:00',
    end='2026-05-04T12:30:00',
    frequency='DAILY',
    count=5,   # 5 Mal insgesamt
)
```

### Wöchentlich an bestimmten Tagen

```python
# Jeden Montag und Mittwoch, 10 Mal
cal.create_recurring_event(
    title='Stand-up Meeting',
    start='2026-05-04T09:00:00',
    end='2026-05-04T09:15:00',
    frequency='WEEKLY',
    days_of_week=['MO', 'WE'],
    count=10,
    color='peacock',
    reminders=[{'method': 'popup', 'minutes': 5}],
)
```

### Jeden Monat (bis zu einem Datum)

```python
cal.create_recurring_event(
    title='Monatliches Reporting',
    start='2026-05-01T10:00:00',
    end='2026-05-01T11:00:00',
    frequency='MONTHLY',
    until='20261201',   # bis Dezember 2026
    color='grape',
)
```

### Alle 2 Wochen

```python
cal.create_recurring_event(
    title='Sprint Review',
    start='2026-05-08T14:00:00',
    end='2026-05-08T15:00:00',
    frequency='WEEKLY',
    interval=2,   # alle 2 Wochen
    count=12,
)
```

### Wochentags-Codes

| Code | Tag       |
|------|-----------|
| `MO` | Montag    |
| `TU` | Dienstag  |
| `WE` | Mittwoch  |
| `TH` | Donnerstag |
| `FR` | Freitag   |
| `SA` | Samstag   |
| `SU` | Sonntag   |

---

## 10. Duplikate verwalten

```python
# Duplikate nur anzeigen
duplicates = cal.find_duplicates(max_results=100)
cal.print_events(duplicates)

# Duplikate direkt löschen
deleted = cal.delete_duplicates()
print(f"{deleted} Duplikate gelöscht.")
```

---

## 11. Kalender-Verwaltung

### Alle Kalender anzeigen

```python
calendars = cal.list_calendars()

# Kalender-IDs ausgeben
for c in calendars:
    print(c['id'], '—', c['summary'])
```

### Verfügbare Farben anzeigen

```python
# Zeigt Farben aus der API (mit Hex-Codes)
cal.get_available_colors()

# Zeigt die Namen die du im Code verwenden kannst
cal.print_colors()
```

---

## 12. Farben-Referenz

Übergebe den **Namen** (links) an den `color=` Parameter:

| Parameter-Wert | Farbe                    | Hex-Code  |
|----------------|--------------------------|-----------|
| `lavender`     | 💜 Lavendel (Hellblau)   | `#a4bdfc` |
| `sage`         | 🟢 Salbei (Grün/Teal)    | `#7ae7bf` |
| `grape`        | 🟣 Traube (Lila)         | `#dbadff` |
| `flamingo`     | 🩷 Flamingo (Pink/Coral) | `#ff887c` |
| `banana`       | 🟡 Banane (Gelb)         | `#fbd75b` |
| `tangerine`    | 🟠 Mandarine (Orange)    | `#ffb878` |
| `peacock`      | 🔵 Pfau (Cyan/Türkis)    | `#46d6db` |
| `graphite`     | ⬛ Graphit (Grau)         | `#e1e1e1` |
| `blueberry`    | 💙 Blaubeere (Dunkelblau)| `#5484ed` |
| `green`        | 🟩 Grün (Dunkelgrün)     | `#51b749` |
| `tomato`       | ❤️ Tomate (Rot)          | `#dc2127` |

**Beispiele:**
```python
color='tomato'      # Dringende Termine
color='banana'      # Feiertage / Urlaub
color='blueberry'   # Arzt-Termine
color='sage'        # Erledigte Aufgaben
color='graphite'    # Abgesagte Events
```

---

## 13. Erinnerungen-Referenz

### Methoden

| `method`        | Beschreibung                         |
|-----------------|--------------------------------------|
| `'popup'`       | Pop-up Benachrichtigung (Standard)   |
| `'email'`       | E-Mail-Benachrichtigung              |

### Minuten-Werte

| Minuten | Bedeutung        |
|---------|------------------|
| `10`    | 10 Minuten vorher|
| `15`    | 15 Minuten vorher|
| `30`    | 30 Minuten vorher|
| `60`    | 1 Stunde vorher  |
| `120`   | 2 Stunden vorher |
| `1440`  | 1 Tag vorher     |
| `2880`  | 2 Tage vorher    |
| `10080` | 1 Woche vorher   |

### Beispiel mit mehreren Erinnerungen

```python
reminders=[
    {'method': 'popup', 'minutes': 10},     # 10 Min vorher — Pop-up
    {'method': 'email', 'minutes': 1440},   # 1 Tag vorher — E-Mail
    {'method': 'popup', 'minutes': 10080},  # 1 Woche vorher — Pop-up
]
```

---

## 14. Vollständiges Beispiel

```python
"""
Vollständiges Beispiel — zeigt alle wichtigen Funktionen der Bibliothek.
"""
from datetime import date, datetime, timedelta
from google_calendar import GoogleCalendar

# ── 1. Verbindung herstellen ──────────────────────────────────────────────
cal = GoogleCalendar()


# ── 2. Kalender anzeigen ─────────────────────────────────────────────────
print("\n=== Meine Kalender ===")
cal.list_calendars()


# ── 3. Kommende Events anzeigen ───────────────────────────────────────────
print("\n=== Nächste 10 Events ===")
events = cal.get_upcoming_events(10)
cal.print_events(events)
cal.print_summary(events)


# ── 4. Einfaches Event erstellen ──────────────────────────────────────────
cal.create_event(
    title='Team Meeting',
    start='2026-05-05T10:00:00',
    end='2026-05-05T11:00:00',
    location='Konferenzraum A',
    description='Wöchentliches Team-Meeting. Agenda in Slack.',
    color='peacock',
    reminders=[
        {'method': 'popup', 'minutes': 15},
        {'method': 'email', 'minutes': 60},
    ],
)


# ── 5. Ganztages-Event erstellen ──────────────────────────────────────────
cal.create_all_day_event(
    title='Betriebsausflug',
    day='2026-05-20',
    location='Spreewald, Brandenburg',
    description='Treffpunkt 08:00 Uhr am Haupteingang.',
    color='banana',
)


# ── 6. Wiederkehrendes Event erstellen ────────────────────────────────────
cal.create_recurring_event(
    title='Daily Stand-up',
    start='2026-05-04T09:00:00',
    end='2026-05-04T09:15:00',
    frequency='WEEKLY',
    days_of_week=['MO', 'TU', 'WE', 'TH', 'FR'],  # Montag-Freitag
    count=20,
    color='sage',
    reminders=[{'method': 'popup', 'minutes': 5}],
)


# ── 7. Event suchen und bearbeiten ────────────────────────────────────────
event = cal.get_event_by_title("Team Meeting")
if event:
    cal.update_event(
        event_id=event['id'],
        title='Team Meeting — VERSCHOBEN',
        start='2026-05-05T14:00:00',
        end='2026-05-05T15:00:00',
        description='Verschoben auf 14 Uhr! Bitte anpassen.',
        color='tangerine',
    )


# ── 8. Kurzform: direkt per Titel bearbeiten ─────────────────────────────
cal.update_event_by_title(
    'Betriebsausflug',
    description='HINWEIS: Regenjacke einpacken! Treffpunkt 08:00.',
)


# ── 9. Events in Zeitraum lesen ───────────────────────────────────────────
print("\n=== Events im Mai 2026 ===")
mai_events = cal.get_events_in_range(date(2026, 5, 1), date(2026, 5, 31))
cal.print_summary(mai_events)


# ── 10. Nach Keyword suchen ───────────────────────────────────────────────
print("\n=== Events mit 'Meeting' ===")
meetings = cal.search_events("Meeting")
cal.print_summary(meetings)


# ── 11. Duplikate bereinigen ──────────────────────────────────────────────
duplicates = cal.find_duplicates()
if duplicates:
    cal.print_events(duplicates)
    cal.delete_duplicates()


# ── 12. Einzelnes Event löschen ───────────────────────────────────────────
event = cal.get_event_by_title("Team Meeting — VERSCHOBEN")
if event:
    cal.delete_event(event['id'])


# ── 13. Alle Events mit bestimmtem Titel löschen ─────────────────────────
# Vorsicht: löscht ALLE passenden Events!
# cal.delete_all_by_title("Test")


# ── 14. Farben anzeigen ───────────────────────────────────────────────────
cal.print_colors()
```

---

## 15. Batch-Requests (viele Änderungen auf einmal)

Jeder einzelne `create_event()` / `update_event()` / `delete_event()`-Aufruf ist
ein eigener HTTP-Request an Google (~0,3–1s Latenz). Wenn du viele Events auf
einmal anlegst/änderst/löschst, bündelt `new_batch()` sie in **einen** Request:

```python
batch = cal.new_batch()
batch.create_event(title="Schicht", start="2026-05-05T08:00:00", end="2026-05-05T16:00:00")
batch.update_event(event_id="abc123", color="tomato")
batch.delete_event(event_id="def456")

results = batch.execute()          # genau ein HTTP-Request für alle drei
for r in results:
    if not r.ok:
        print("fehlgeschlagen:", r.error)
```

- Reihenfolge der `results` entspricht der Reihenfolge, in der die Aufrufe
  hinzugefügt wurden.
- `update_event()` im Batch nutzt PATCH (nur die übergebenen Felder ändern
  sich) statt GET+PUT — dadurch ersetzt ein übergebenes `extended_properties`
  das bestehende komplett, statt es hineinzumischen wie beim normalen
  `update_event()`. Also immer alle gewünschten Keys mitgeben.
- Limit: bis zu 1000 Aufrufe pro Batch (Google-API-Grenze).
- In diesem Projekt nutzt [`calendar_sync.py`](calendar_sync.py) das für den
  Zeitnachweis-Sync — ein Monat mit 12 Schichten braucht dadurch einen statt
  zwölf Requests.

---

## 16. Fehlerbehebung

### `FileNotFoundError: credentials.json not found`
→ Du hast die `credentials.json` noch nicht heruntergeladen.  
Folge Schritt 2 in diesem Guide.

### `token.pickle ist ungültig / Permission denied`
→ Lösche die `token.pickle` Datei und führe das Script neu aus.  
Ein neues Browser-Fenster öffnet sich zur erneuten Authentifizierung.

### `Scopes haben sich geändert`
→ Wenn du die `SCOPES`-Variable in `google_calendar.py` änderst, **musst** du  
`token.pickle` löschen, damit ein neues Token mit den neuen Berechtigungen erstellt wird.

### `HttpError 403: Calendar usage limits exceeded`
→ Die Google Calendar API hat kostenlose Limits.  
Warte kurz und versuche es erneut, oder reduziere `max_results`.

### `HttpError 404: Not Found`
→ Die Event-ID ist ungültig oder das Event wurde bereits gelöscht.

### Event erscheint nicht in der App
→ Stelle sicher, dass `timezone` korrekt gesetzt ist (Standard: `Europe/Berlin`).  
Überprüfe auch, ob du den richtigen Kalender (`calendar_id`) verwendest.

### Token läuft ab
→ Das Token wird **automatisch** erneuert solange `refresh_token` gültig ist.  
Falls nicht: `token.pickle` löschen und neu authentifizieren.

---

## 🔗 Weitere Ressourcen

- [Google Calendar API Dokumentation](https://developers.google.com/calendar/api/v3/reference)
- [Google Cloud Console](https://console.cloud.google.com/)
- [IANA Zeitzonen-Liste](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)
- [Python Client Library](https://github.com/googleapis/google-api-python-client)
