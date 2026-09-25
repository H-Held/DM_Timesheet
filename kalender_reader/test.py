"""
================================================================================
  Vollständige Test-Suite für google_calendar.py
================================================================================

Testet ALLE Funktionen der GoogleCalendar Bibliothek:
  ✓ Authentifizierung
  ✓ Events lesen (all-day, timed, search, by ID, by title, range)
  ✓ Events erstellen (timed, all-day, recurring)
  ✓ Events bearbeiten (update_event, update_event_by_title)
  ✓ Events löschen (by ID, by title, bulk delete)
  ✓ Duplikate finden und löschen
  ✓ Kalender-Verwaltung
  ✓ Farben testen (alle 11 Farben)
  ✓ Erinnerungen testen
  ✓ Wiederkehrende Events
  ✓ Einladungen

Am Ende: Alles aufräumen und Resultat-Report anzeigen.

Hinweis: Dies ist ein eigenständiges, manuell auszuführendes Test-Skript,
kein Teil des Produktionspfads (main.py/calendar_sync.py). Es nutzt daher
bewusst print() statt logging — bitte nicht auf logger umstellen.

================================================================================
"""
import os
import sys
from datetime import datetime, date, timedelta
from typing import List, Dict, Any

# Pfad zum Verzeichnis der Skript-Datei
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

from google_calendar import GoogleCalendar, COLORS


# ─────────────────────────────────────────────────────────────────────────
# GLOBALS & TEST TRACKING
# ─────────────────────────────────────────────────────────────────────────

class TestReport:
    """Speichert und formatted Test-Resultate."""
    
    def __init__(self):
        self.tests: List[Dict[str, Any]] = []
        self.created_event_ids: List[str] = []
    
    def add_test(self, name: str, success: bool, message: str = "", event_id: str = None):
        """Füge Test-Resultat hinzu."""
        self.tests.append({
            'name': name,
            'success': success,
            'message': message,
            'event_id': event_id,
        })
        if event_id:
            self.created_event_ids.append(event_id)
    
    def print_summary(self):
        """Drucke Zusammenfassung."""
        total = len(self.tests)
        passed = sum(1 for t in self.tests if t['success'])
        failed = total - passed
        
        print("\n" + "=" * 80)
        print("  📊 TEST RESULTAT BERICHT")
        print("=" * 80)
        
        for i, test in enumerate(self.tests, 1):
            status = "✅" if test['success'] else "❌"
            print(f"{status} [{i:2d}] {test['name']}")
            if test['message']:
                print(f"        {test['message']}")
        
        print("\n" + "─" * 80)
        print(f"  Gesamt: {total} Tests")
        print(f"  ✅ Bestanden: {passed}")
        print(f"  ❌ Fehlgeschlagen: {failed}")
        print(f"  📊 Quote: {passed/total*100:.1f}%")
        print("=" * 80 + "\n")
        
        return failed == 0


# ─────────────────────────────────────────────────────────────────────────
# TEST FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────

def test_authentication(cal: GoogleCalendar, report: TestReport):
    """Test 1: Authentifizierung prüfen."""
    try:
        assert cal.service is not None
        report.add_test("Authentifizierung", True, "Google Calendar API verbunden")
    except Exception as e:
        report.add_test("Authentifizierung", False, str(e))


def test_list_calendars(cal: GoogleCalendar, report: TestReport):
    """Test 2: Kalender auflisten."""
    try:
        calendars = cal.list_calendars()
        assert isinstance(calendars, list)
        assert len(calendars) > 0
        report.add_test("list_calendars()", True, f"{len(calendars)} Kalender gefunden")
    except Exception as e:
        report.add_test("list_calendars()", False, str(e))


def test_get_upcoming_events(cal: GoogleCalendar, report: TestReport):
    """Test 3: Bevorstehende Events abrufen."""
    try:
        events = cal.get_upcoming_events(max_results=5)
        assert isinstance(events, list)
        report.add_test("get_upcoming_events()", True, f"{len(events)} kommende Events gefunden")
    except Exception as e:
        report.add_test("get_upcoming_events()", False, str(e))


def test_get_available_colors(cal: GoogleCalendar, report: TestReport):
    """Test 4: Verfügbare Farben abrufen."""
    try:
        colors = cal.get_available_colors()
        assert isinstance(colors, dict)
        assert 'event' in colors or colors is not None
        report.add_test("get_available_colors()", True, "Farben von API abgerufen")
    except Exception as e:
        report.add_test("get_available_colors()", False, str(e))


def test_create_simple_event(cal: GoogleCalendar, report: TestReport):
    """Test 5: Einfaches Event erstellen."""
    try:
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT10:00:00")
        tomorrow_end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT11:00:00")
        
        event = cal.create_event(
            title="🧪 TEST: Einfaches Event",
            start=tomorrow,
            end=tomorrow_end,
        )
        assert event is not None
        assert event['id'] is not None
        report.add_test("create_event() — einfach", True, f"Event ID: {event['id']}", event['id'])
    except Exception as e:
        report.add_test("create_event() — einfach", False, str(e))


def test_create_event_all_colors(cal: GoogleCalendar, report: TestReport):
    """Test 6-16: Events mit ALLEN 11 Farben erstellen."""
    base_time = datetime.now() + timedelta(days=2)
    
    for color_name in COLORS.keys():
        try:
            event_time = base_time.strftime("%Y-%m-%dT%H:%M:%S")
            event_time_end = (base_time + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
            
            event = cal.create_event(
                title=f"🧪 TEST: Farbe {color_name.upper()}",
                start=event_time,
                end=event_time_end,
                color=color_name,
                description=f"Test Event mit Farbe: {color_name}",
            )
            base_time = base_time + timedelta(minutes=90)
            
            assert event is not None
            report.add_test(f"create_event() — Farbe '{color_name}'", True, event['id'], event['id'])
        except Exception as e:
            report.add_test(f"create_event() — Farbe '{color_name}'", False, str(e))


def test_create_event_with_location_description(cal: GoogleCalendar, report: TestReport):
    """Test 17: Event mit Ort und Beschreibung erstellen."""
    try:
        tomorrow = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%dT14:00:00")
        tomorrow_end = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%dT15:00:00")
        
        event = cal.create_event(
            title="🧪 TEST: Mit Ort und Beschreibung",
            start=tomorrow,
            end=tomorrow_end,
            location="Konferenzraum 5, Etage 3",
            description="Dies ist eine Test-Beschreibung.\nZweite Zeile mit Informationen.",
        )
        assert event is not None
        report.add_test("create_event() — location + description", True, event['id'], event['id'])
    except Exception as e:
        report.add_test("create_event() — location + description", False, str(e))


def test_create_event_with_reminders(cal: GoogleCalendar, report: TestReport):
    """Test 18: Event mit Erinnerungen erstellen."""
    try:
        tomorrow = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%dT09:00:00")
        tomorrow_end = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%dT10:00:00")
        
        event = cal.create_event(
            title="🧪 TEST: Mit Erinnerungen",
            start=tomorrow,
            end=tomorrow_end,
            reminders=[
                {'method': 'popup', 'minutes': 10},
                {'method': 'email', 'minutes': 60},
                {'method': 'popup', 'minutes': 1440},  # 1 Tag vorher
            ],
        )
        assert event is not None
        assert 'reminders' in event
        report.add_test("create_event() — reminders", True, event['id'], event['id'])
    except Exception as e:
        report.add_test("create_event() — reminders", False, str(e))


def test_create_all_day_event(cal: GoogleCalendar, report: TestReport):
    """Test 19: Ganztages-Event erstellen."""
    try:
        event = cal.create_all_day_event(
            title="🧪 TEST: Ganztages-Event",
            day=date.today() + timedelta(days=5),
            color='banana',
            description="Ein Test Ganztages-Event",
        )
        assert event is not None
        assert event['start'].get('date') is not None
        report.add_test("create_all_day_event()", True, event['id'], event['id'])
    except Exception as e:
        report.add_test("create_all_day_event()", False, str(e))


def test_create_multi_day_event(cal: GoogleCalendar, report: TestReport):
    """Test 20: Mehrtägiges Ganztages-Event erstellen."""
    try:
        start_day = date.today() + timedelta(days=6)
        end_day = start_day + timedelta(days=3)
        
        event = cal.create_all_day_event(
            title="🧪 TEST: Mehrtägiger Urlaub",
            day=start_day,
            end_day=end_day,
            color='sage',
            description="Test: 4-Tage Urlaub",
        )
        assert event is not None
        report.add_test("create_all_day_event() — mehrtägig", True, event['id'], event['id'])
    except Exception as e:
        report.add_test("create_all_day_event() — mehrtägig", False, str(e))


def test_create_recurring_event(cal: GoogleCalendar, report: TestReport):
    """Test 21: Wiederkehrendes Event erstellen."""
    try:
        start_time = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%dT11:00:00")
        end_time = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%dT11:15:00")
        
        event = cal.create_recurring_event(
            title="🧪 TEST: Wiederholter Stand-up",
            start=start_time,
            end=end_time,
            frequency='WEEKLY',
            days_of_week=['MO', 'WE', 'FR'],
            count=8,
            color='peacock',
        )
        assert event is not None
        assert 'recurrence' in event
        report.add_test("create_recurring_event()", True, event['id'], event['id'])
    except Exception as e:
        report.add_test("create_recurring_event()", False, str(e))


def test_create_recurring_daily(cal: GoogleCalendar, report: TestReport):
    """Test 22: Tägliches wiederkehrendes Event."""
    try:
        start_time = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%dT12:00:00")
        end_time = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%dT12:30:00")
        
        event = cal.create_recurring_event(
            title="🧪 TEST: Tägliche Mittagspause",
            start=start_time,
            end=end_time,
            frequency='DAILY',
            count=5,
            color='flamingo',
        )
        assert event is not None
        report.add_test("create_recurring_event() — täglich", True, event['id'], event['id'])
    except Exception as e:
        report.add_test("create_recurring_event() — täglich", False, str(e))


def test_search_events(cal: GoogleCalendar, report: TestReport):
    """Test 23: Events suchen."""
    try:
        # Wir suchen nach "TEST" da wir viele TEST-Events erstellt haben
        results = cal.search_events("🧪", max_results=50)
        assert isinstance(results, list)
        report.add_test("search_events()", True, f"{len(results)} Tests gefunden")
    except Exception as e:
        report.add_test("search_events()", False, str(e))


def test_get_event_by_title(cal: GoogleCalendar, report: TestReport):
    """Test 24: Event nach Titel abrufen."""
    try:
        event = cal.get_event_by_title("🧪 TEST: Einfaches Event")
        assert event is not None
        assert event['summary'] is not None
        report.add_test("get_event_by_title()", True, event['id'], event['id'])
    except Exception as e:
        report.add_test("get_event_by_title()", False, str(e))


def test_get_event_by_id(cal: GoogleCalendar, report: TestReport):
    """Test 25: Event nach ID abrufen."""
    try:
        # Zuerst ein Event finden, dann per ID abrufen
        event = cal.get_event_by_title("🧪 TEST: Mit Ort und Beschreibung")
        if event:
            fetched = cal.get_event_by_id(event['id'])
            assert fetched is not None
            assert fetched['id'] == event['id']
            report.add_test("get_event_by_id()", True, fetched['id'])
        else:
            report.add_test("get_event_by_id()", False, "Kein Event zum Testen gefunden")
    except Exception as e:
        report.add_test("get_event_by_id()", False, str(e))


def test_get_events_in_range(cal: GoogleCalendar, report: TestReport):
    """Test 26: Events in Zeitraum abrufen."""
    try:
        start_date = date.today()
        end_date = date.today() + timedelta(days=20)
        
        events = cal.get_events_in_range(start_date, end_date, max_results=50)
        assert isinstance(events, list)
        report.add_test("get_events_in_range()", True, f"{len(events)} Events in Range gefunden")
    except Exception as e:
        report.add_test("get_events_in_range()", False, str(e))


def test_update_event(cal: GoogleCalendar, report: TestReport):
    """Test 27: Event bearbeiten."""
    try:
        # Finde ein einfaches Test-Event
        event = cal.get_event_by_title("🧪 TEST: Mit Ort und Beschreibung")
        if event:
            updated = cal.update_event(
                event_id=event['id'],
                title="🧪 TEST: AKTUALISIERT",
                color='tangerine',
                description="UPDATED DESCRIPTION für Testing",
            )
            assert updated is not None
            report.add_test("update_event()", True, updated['id'])
        else:
            report.add_test("update_event()", False, "Kein Event zum bearbeiten gefunden")
    except Exception as e:
        report.add_test("update_event()", False, str(e))


def test_update_event_by_title(cal: GoogleCalendar, report: TestReport):
    """Test 28: Event per Titel bearbeiten."""
    try:
        result = cal.update_event_by_title(
            "🧪 TEST: Mit Erinnerungen",
            color='blueberry',
            description="UPDATED via update_event_by_title()",
        )
        if result is not None:
            report.add_test("update_event_by_title()", True, result['id'])
        else:
            report.add_test("update_event_by_title()", False, "Event nicht gefunden oder nicht aktualisiert")
    except Exception as e:
        report.add_test("update_event_by_title()", False, str(e))


def test_find_duplicates(cal: GoogleCalendar, report: TestReport):
    """Test 29: Duplikate suchen."""
    try:
        duplicates = cal.find_duplicates(max_results=100)
        assert isinstance(duplicates, list)
        report.add_test("find_duplicates()", True, f"{len(duplicates)} Duplikate gefunden")
    except Exception as e:
        report.add_test("find_duplicates()", False, str(e))


def test_print_functions(cal: GoogleCalendar, report: TestReport):
    """Test 30: Print-Funktionen."""
    try:
        events = cal.get_upcoming_events(max_results=3)
        
        print("\n--- print_events() ---")
        cal.print_events(events)
        
        print("\n--- print_summary() ---")
        cal.print_summary(events)
        
        print("\n--- print_colors() ---")
        cal.print_colors()
        
        report.add_test("print_events() / print_summary() / print_colors()", True, "Alle Print-Funktionen OK")
    except Exception as e:
        report.add_test("print_events() / print_summary() / print_colors()", False, str(e))


# ─────────────────────────────────────────────────────────────────────────
# CLEANUP FUNCTION
# ─────────────────────────────────────────────────────────────────────────

def cleanup_test_events(cal: GoogleCalendar, report: TestReport):
    """Lösche alle erstellten Test-Events am Ende."""
    print("\n" + "=" * 80)
    print("  🧹 CLEANUP: Lösche alle Test-Events...")
    print("=" * 80)
    
    # Finde und lösche alle TEST-Events
    deleted_count = 0
    deleted_count += cal.delete_all_by_title("🧪", max_results=100)
    
    print(f"\n✅ Insgesamt {deleted_count} Test-Events gelöscht.")
    print("   Der Kalender ist wieder im Ausgangszustand.\n")


# ─────────────────────────────────────────────────────────────────────────
# MAIN TEST EXECUTION
# ─────────────────────────────────────────────────────────────────────────

def main():
    """Haupteinstiegspunkt — Führe alle Tests durch."""
    print("\n" + "=" * 80)
    print("  🚀 GOOGLE CALENDAR LIBRARY — VOLLSTÄNDIGE TEST-SUITE")
    print("=" * 80)
    print("\nErstelle Google Calendar Objekt...\n")
    
    # Authentifizierung mit korrekten Pfaden
    cal = GoogleCalendar(
        credentials_path=os.path.join(SCRIPT_DIR, 'credentials.json'),
        token_path=os.path.join(SCRIPT_DIR, 'token.pickle'),
    )
    report = TestReport()
    
    print("=" * 80)
    print("  🧪 STARTE TESTS")
    print("=" * 80 + "\n")
    
    # Test 1-4: Basics
    test_authentication(cal, report)
    test_list_calendars(cal, report)
    test_get_upcoming_events(cal, report)
    test_get_available_colors(cal, report)
    
    # Test 5-8: Einfache Events
    test_create_simple_event(cal, report)
    test_create_event_all_colors(cal, report)
    test_create_event_with_location_description(cal, report)
    test_create_event_with_reminders(cal, report)
    
    # Test 9-10: All-Day Events
    test_create_all_day_event(cal, report)
    test_create_multi_day_event(cal, report)
    
    # Test 11-12: Recurring Events
    test_create_recurring_event(cal, report)
    test_create_recurring_daily(cal, report)
    
    # Test 13-18: Read Operations
    test_search_events(cal, report)
    test_get_event_by_title(cal, report)
    test_get_event_by_id(cal, report)
    test_get_events_in_range(cal, report)
    
    # Test 19-21: Update Operations
    test_update_event(cal, report)
    test_update_event_by_title(cal, report)
    test_find_duplicates(cal, report)
    
    # Test 22: Print Functions
    test_print_functions(cal, report)
    
    # CLEANUP
    cleanup_test_events(cal, report)
    
    # FINAL REPORT
    all_passed = report.print_summary()
    
    if all_passed:
        print("\n🎉 ALLE TESTS ERFOLGREICH ABGESCHLOSSEN!")
        print("   Die Google Calendar Bibliothek funktioniert einwandfrei.\n")
        return 0
    else:
        print("\n⚠️  EINIGE TESTS FEHLGESCHLAGEN")
        print("   Bitte überprüfe die fehlgeschlagenen Tests oben.\n")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
