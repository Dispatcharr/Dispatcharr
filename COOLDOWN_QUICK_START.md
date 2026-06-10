# Stream Cooldown System - Quick Start

## Was ist das?

Ein Cooldown-System das verhindert, dass Dispatcharr endlos dieselben fehlgeschlagenen Stream/Profile-Kombinationen probiert.

**Problem ohne Cooldown:**
```
Profile 340 → Fehler
Profile 341 → Fehler  
Profile 342 → Fehler
→ System steckt fest, keine neuen Versuche möglich
```

**Lösung mit Cooldown:**
```
Profile 340 → Fehler → 10min Sperre
Profile 341 → Fehler → 10min Sperre
Profile 342 → Fehler → 10min Sperre
→ Alle gesperrt → RESET → Versuche alles nochmal
→ Wenn wieder alle fehlschlagen → gibt auf (KEINE Endlosschleife!)
```

---

## Aktivierung

### 1. UI öffnen
```
Settings → Proxy Settings
```

### 2. Cooldown aktivieren
```
☑ Stream Cooldown Enabled
```

### 3. Dauer einstellen (optional)
```
Stream Cooldown Duration: 10 minutes (Standard)
```

Empfohlene Werte:
- **5-10 Minuten:** Normale IPTV-Provider
- **15-30 Minuten:** Sehr instabile Provider
- **1-3 Minuten:** Schnelles Testing

### 4. Speichern
```
[Save] Button klicken
```

---

## Logs überwachen

### Cooldown gesetzt:
```bash
[COOLDOWN] Set cooldown for stream 708953/profile 340 on channel ... for 10m 0s
```

### Cooldown übersprungen:
```bash
[COOLDOWN] Skipped 2 combinations on cooldown for channel ...
[COOLDOWN] Skipping stream 708953/profile 341 - blocked for 8m 23s more
```

### Last Resort (alle Cooldowns gelöscht):
```bash
[COOLDOWN] Last resort: cleared 6 cooldown(s) for channel ... - retrying all combinations
```

---

## Wann aktivieren?

✅ **JA aktivieren wenn:**
- IPTV-Provider mit häufigen Ausfällen
- Viele Streams/Profiles pro Channel
- Endlosschleifen in Logs sichtbar
- Provider beschwert sich über zu viele Requests

❌ **NEIN deaktivieren wenn:**
- Eigener stabiler Server
- Wenige Streams/Profiles
- Schnelles Failover gewünscht
- Testing/Debugging

---

## Default-Verhalten

**Per Default ist Cooldown DEAKTIVIERT!**

- Verhält sich wie v0.26.0 ohne Cooldown
- Keine Breaking Changes
- Opt-In Feature

---

## Manuelle Cooldown-Löschung (via Redis)

```bash
# Alle Cooldowns für alle Channels löschen
redis-cli --scan --pattern "live:channel:*:cooldown:*" | xargs redis-cli del

# Cooldowns für einen spezifischen Channel löschen
redis-cli --scan --pattern "live:channel:{UUID}:cooldown:*" | xargs redis-cli del

# Cooldown für eine spezifische Stream+Profile Kombination löschen
redis-cli del "live:channel:{UUID}:cooldown:{stream_id}:{profile_id}"
```

---

## Testing

### Test 1: Cooldown deaktiviert (Default)
```bash
# Sollte sich wie vorher verhalten
# Keine [COOLDOWN] Logs
```

### Test 2: Cooldown aktiviert
```bash
# [COOLDOWN] Logs sollten erscheinen
# Übersprungene Kombinationen sichtbar
```

### Test 3: Last Resort Trigger
```bash
# Alle Profile fehlschlagen lassen
# Nach 2-3 Durchläufen sollte Last Resort triggern
# Log: "[COOLDOWN] Last resort: cleared X cooldown(s)"
```

---

## Troubleshooting

### Problem: Cooldown funktioniert nicht

**Check 1:** Cooldown aktiviert?
```bash
# UI: Settings → Proxy Settings
# ☑ Stream Cooldown Enabled?
```

**Check 2:** Redis läuft?
```bash
redis-cli ping
# Sollte: PONG
```

**Check 3:** Logs prüfen
```bash
# Sollte enthalten: "[COOLDOWN]"
# Wenn nicht → Feature nicht aktiviert
```

### Problem: Zu viele Cooldowns

**Lösung 1:** Cooldown-Zeit reduzieren
```bash
# UI: Stream Cooldown Duration → 5 minutes (statt 10)
```

**Lösung 2:** Cooldowns manuell löschen
```bash
redis-cli --scan --pattern "live:channel:*:cooldown:*" | xargs redis-cli del
```

### Problem: Stream gibt zu schnell auf

**Lösung:** Cooldown-Zeit erhöhen
```bash
# UI: Stream Cooldown Duration → 15 minutes (statt 10)
# Gibt Provider mehr Zeit sich zu erholen
```

---

## FAQ

**Q: Kann ich Cooldown für einzelne Channels aktivieren?**  
A: Nein, Cooldown ist global für alle Channels. Aber Du kannst es jederzeit ein/ausschalten.

**Q: Was passiert mit laufenden Streams wenn ich Cooldown aktiviere?**  
A: Nichts. Cooldown greift nur bei neuen Fehlern. Laufende Streams bleiben unberührt.

**Q: Löscht Channel-Neustart die Cooldowns?**  
A: Nein! Cooldowns sind Redis-basiert und überleben Channel-Restarts.

**Q: Was ist "Last Resort"?**  
A: Wenn alle Kombinationen auf Cooldown sind, löscht das System ALLE Cooldowns und versucht alles nochmal. Das verhindert Endlosschleifen.

---

## Zusammenfassung

1. **Settings → Proxy Settings**
2. **☑ Stream Cooldown Enabled**
3. **Stream Cooldown Duration: 10 minutes**
4. **[Save]**
5. **Logs überwachen: `[COOLDOWN]` sollte erscheinen**

✅ Endlosschleifen verhindert  
✅ Provider-Last reduziert  
✅ Automatisches Retry nach Cooldown-Zeit  
✅ Konfigurierbar via UI  

**Per Default deaktiviert - keine Breaking Changes!**
