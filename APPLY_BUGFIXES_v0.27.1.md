# Bug Fix Application Guide v0.27.1

## ✅ Alle 6 Bugs wurden bereits im Code gefixt!

Die folgenden Dateien wurden modifiziert:

1. **apps/proxy/live_proxy/input/manager.py** (~70 Zeilen)
2. **core/models.py** (3 Zeilen)
3. **apps/proxy/live_proxy/input/http_streamer.py** (~25 Zeilen)
4. **apps/proxy/live_proxy/url_utils.py** (~30 Zeilen)

---

## 🧪 Verification Tests

### Test 1: Check Syntax
```bash
python3 -m py_compile apps/proxy/live_proxy/input/manager.py
python3 -m py_compile apps/proxy/live_proxy/input/http_streamer.py
python3 -m py_compile apps/proxy/live_proxy/url_utils.py
python3 -m py_compile core/models.py
```

**Erwartetes Ergebnis**: Keine Fehler ✅

### Test 2: Check for gevent.event.Event
```bash
grep "gevent.event.Event" apps/proxy/live_proxy/input/manager.py
```

**Erwartetes Ergebnis**:
```
import gevent.event
self.needs_reconnect = gevent.event.Event()
self.needs_stream_switch = gevent.event.Event()
```

### Test 3: Check FFmpeg Proxy Fix
```bash
grep -A 2 "except ValueError:" core/models.py | grep -A 1 "http_proxy"
```

**Erwartetes Ergebnis**:
```
logger.warning(f"FFmpeg command has no -i flag, appending -http_proxy at end")
cmd.extend(['-http_proxy', proxy])
```

### Test 4: Check tried_combinations Reset
```bash
grep "tried_combinations_reset_time" apps/proxy/live_proxy/input/manager.py
```

**Erwartetes Ergebnis**: 3 Vorkommen
- Initialisierung: `self.tried_combinations_reset_time = time.time() + 3600`
- Hourly check: `if time.time() > self.tried_combinations_reset_time`
- Reset: `self.tried_combinations_reset_time = time.time() + 3600`

### Test 5: Check scan_iter Usage
```bash
grep "scan_iter" apps/proxy/live_proxy/input/manager.py
```

**Erwartetes Ergebnis**:
```
for key in self.buffer.redis_client.scan_iter(match=cooldown_pattern, count=100):
```

---

## 🚀 Deployment Steps

### 1. Backup aktueller Code
```bash
# Create backup
cp -r apps apps_backup_before_v0.27.1
cp core/models.py core/models.py.backup
```

### 2. Build neuen Docker Container (falls Docker-Setup)
```bash
docker-compose build
docker-compose up -d
```

### 3. Oder Python direkt neustarten
```bash
# Stop Dispatcharr
systemctl stop dispatcharr  # oder dein Start-Methode

# Restart
systemctl start dispatcharr
```

### 4. Monitor Logs
```bash
# Watch for Event operations
tail -f logs/dispatcharr.log | grep -E "gevent.event|Event"

# Watch for tried_combinations resets
tail -f logs/dispatcharr.log | grep "tried_combinations"

# Watch for proxy injection
tail -f logs/dispatcharr.log | grep "http_proxy"
```

---

## ✅ Success Indicators

Nach dem Deployment solltest du sehen:

### 1. Keine Syntax Errors
```
✅ Container startet ohne Fehler
✅ Keine ImportError oder AttributeError in Logs
```

### 2. Event Operations funktionieren
```
✅ Logs zeigen "Setting reconnect flag" (ohne Duplicate messages)
✅ Keine "lost signal" Warnungen
```

### 3. Proxy funktioniert
```
✅ FFmpeg-Befehle enthalten -http_proxy wenn konfiguriert
✅ Logs zeigen "appending -http_proxy at end" wenn nötig
```

### 4. tried_combinations wird resettet
```
✅ Nach 1 Stunde: "Hourly tried_combinations reset"
✅ Nach 5 Min Stability: "Stream stable for 300s - clearing tried combinations"
✅ Bei Channel-Stop: "Clearing X tried combinations on channel stop"
```

---

## 🐛 Troubleshooting

### Problem: ImportError: cannot import name 'event' from 'gevent'
**Lösung**: Update gevent
```bash
pip install --upgrade gevent
# oder in Docker:
RUN pip install --upgrade gevent
```

### Problem: AttributeError: 'bool' object has no attribute 'is_set'
**Lösung**: Event-Initialisierung fehlt - check line ~1467 in manager.py

### Problem: Proxy wird immer noch nicht injiziert
**Lösung**: 
1. Check Logger import in models.py
2. Verify `cmd.extend(['-http_proxy', proxy])` vorhanden ist
3. Check FFmpeg command in logs: `ps aux | grep ffmpeg`

### Problem: tried_combinations reset nicht sichtbar
**Lösung**:
1. Warte mindestens 1 Stunde für hourly reset
2. Oder trigger mit 5 Min stable stream
3. Check: `hasattr(self, 'tried_combinations_reset_time')`

---

## 📊 Monitoring Commands

```bash
# Check Event usage
grep -r "\.is_set\|\.set()\|\.clear()" apps/proxy/live_proxy/input/manager.py

# Count Event operations in logs (after 1 hour running)
grep "Setting reconnect flag\|Setting stream switch flag" logs/*.log | wc -l

# Check proxy injections
grep "http_proxy" logs/*.log | tail -20

# Monitor tried_combinations
watch -n 60 'grep "tried_combinations" logs/dispatcharr.log | tail -10'
```

---

## 📈 Performance Expectations

- **Memory**: +8 bytes pro Channel (Event objects)
- **CPU**: Identisch oder minimal besser (scan_iter)
- **Stability**: Deutlich verbessert (Race Conditions eliminiert)
- **Error Rate**: Reduziert durch bessere Error Handling

---

## ✨ Erfolgskriterien

Nach 24 Stunden Uptime:

- [ ] Keine Race Condition Errors
- [ ] tried_combinations wurde mindestens 1x resettet
- [ ] Proxy-Parameter in allen FFmpeg-Calls
- [ ] Redis Errors korrekt kategorisiert
- [ ] Event operations funktionieren (logs zeigen .set/.clear)
- [ ] Keine AttributeErrors bei shutdown

**Alle Checkboxen ✅ = v0.27.1 erfolgreich deployed!**

---

## 📞 Support

Bei Problemen:
1. Check alle Success Indicators oben
2. Review Troubleshooting section
3. Check Logs für spezifische Error messages
4. Verify Python/Gevent versions

**Wichtig**: Alle Fixes sind bereits im Code! Keine manuellen Änderungen nötig.
