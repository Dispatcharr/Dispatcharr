# Bug-Analyse Zusammenfassung - Dispatcharr v0.27.0

## 🔴 Kritische Bugs (Sofort beheben!)

### Bug #1: Last Resort löscht tried_combinations nicht
**Problem**: Das Cooldown-System löscht zwar die Redis-Keys, aber nicht die lokale `tried_combinations` Menge.
Dadurch sind nach dem "Last Resort" immer noch alle Kombinationen als "versucht" markiert → Endlosschleife möglich!

**Lösung**: 1 Zeile hinzufügen in `manager.py` Zeile ~2150:
```python
self.tried_combinations.clear()  # ← Diese Zeile fehlt!
```

### Bug #2: Health Monitor Race Condition
**Problem**: Flags wie `needs_reconnect` werden von mehreren Greenlets gleichzeitig gelesen/geschrieben ohne Lock.
→ Verlorene Signale, doppelte Ausführung, unvorhersehbares Verhalten.

**Lösung**: Boolean-Flags durch `gevent.event.Event()` ersetzen.

### Bug #3: FFmpeg Proxy Injection funktioniert nicht
**Problem**: Wenn ffmpeg-Kommando kein `-i` Flag hat, wird Proxy einfach ignoriert (leerer `pass` Block).

**Lösung**: Im `except ValueError` Block den Proxy ans Ende anhängen.

---

## 🟠 Hohe Priorität

### Bug #4: HTTPStreamReader Shutdown Race
**Problem**: Beim Herunterfahren kann `self.response` None werden während der Thread noch zugreift → AttributeError

**Lösung**: Lock um response-Zugriffe oder bessere Exception-Behandlung.

### Bug #5: Redis-Fehler werden ignoriert
**Problem**: Wenn Redis down ist, werden ALLE Profile als "verfügbar" markiert → Connection-Limits werden verletzt.

**Lösung**: Spezifische Redis-Exceptions fangen, Circuit Breaker implementieren.

### Bug #6: Buffer Timeout Failover-Spam
**Problem**: Wenn Buffer nicht gefüllt wird, triggert der Cleanup-Thread alle 5 Sekunden einen Failover,
ohne zu warten ob der vorherige abgeschlossen ist.

**Lösung**: `connection_start_time` zurücksetzen nach Failover-Trigger.

---

## 🟡 Mittlere Priorität

### Bug #7: Redis Scan mit willkürlichem Limit
**Problem**: `max_iterations = 1000` ist willkürlich gewählt, könnte zu unvollständigem Cleanup führen.

**Lösung**: `scan_iter()` verwenden statt manueller Cursor-Verwaltung.

### Bug #8: tried_combinations wird nie geleert
**Problem**: Selbst wenn ein Stream stundenlang funktioniert, bleibt die Kombination in `tried_combinations`.
→ Funktionierende Streams werden permanent "geblockt".

**Lösung**: Reset nach 1 Stunde oder nach 5 Minuten stabilem Stream.

---

## Schnelltest für Bug #1 (Kritisch!)

```bash
# 1. Cooldown aktivieren (Settings → Proxy → Stream Cooldown Enabled)
# 2. Channel starten mit 3 Streams à 2 Profilen
# 3. Provider killen → alle Kombinationen schlagen fehl
# 4. Warten bis Last Resort triggert
# 5. In Logs schauen:

# ❌ BUG: Du wirst sehen dass tried_combinations NICHT geleert wurde
# System kann keine Kombinationen mehr probieren trotz geleerten Cooldowns!
```

---

## Fix-Priorität

1. **SOFORT**: Bug #1 (1 Zeile Code) + Bug #3 (FFmpeg Proxy)
2. **Diese Woche**: Bug #2 (Race Condition) + Bug #6 (Failover-Spam)
3. **Nächster Sprint**: Bug #5 + Bug #8
4. **Bei Gelegenheit**: Bug #4 + Bug #7

---

## Statistik

- **Analysierte Dateien**: 8
- **Geprüfte Zeilen**: ~2.500
- **Gefundene Bugs**: 8
  - 🔴 Kritisch: 3
  - 🟠 Hoch: 3
  - 🟡 Mittel: 2

**Fazit**: Die Features sind **gut designed** aber haben **kritische Implementierungsfehler**.
Das Cooldown-System ist zu 95% fertig - nur die fehlende `tried_combinations.clear()` Zeile macht es wirkungslos!

---

Detaillierte Analyse siehe: `BUG_ANALYSIS_v0.27.0.md`
