# Cooldown Last Resort Fix - Verhindert Endlosschleifen

## Problem

Die aktuelle Cooldown-Implementierung hat KEINEN Counter für Last Resort Attempts.
Das bedeutet Last Resort kann **UNENDLICH OFT** triggern!

## Was ist "Last Resort"?

**Last Resort** = Wenn ALLE Stream+Profile Kombinationen auf Cooldown sind:
1. Lösche ALLE Cooldowns für diesen Channel
2. `tried_combinations.clear()`
3. Probiere ALLE Kombinationen nochmal

## Aktuelles Problem (OHNE Counter)

```python
while True:  # ← Keine Begrenzung!
    probiere alle Kombinationen
    wenn alle fehlschlagen:
        wenn Cooldown enabled:
            Last Resort → clear all → probiere nochmal  ← ENDLOSSCHLEIFE!
```

**Ergebnis:** UNENDLICHE Schleife möglich!

## Lösung (MIT Counter)

```python
last_resort_attempts = 0
max_last_resort_attempts = 2  # = 3 total tries (1 initial + 2 Last Resort)

while last_resort_attempts <= max_last_resort_attempts:
    probiere alle Kombinationen
    wenn alle fehlschlagen:
        wenn Cooldown enabled AND last_resort_attempts < max:
            last_resort_attempts += 1
            Last Resort → clear all → probiere nochmal
            continue  # ← Zurück zum Anfang der while-Loop
        else:
            return False  # ← Gibt auf nach max attempts
```

**Ergebnis:** Maximal 3 Durchläufe (1 initial + 2x Last Resort), dann gibt System auf!

## Code-Änderungen

### 1. While-Loop hinzufügen mit Counter

```python
def _try_next_stream(self):
    try:
        logger.info(f"Trying to find alternative stream...")
        
        # Track Last Resort attempts to prevent infinite loops
        last_resort_attempts = 0
        max_last_resort_attempts = 2  # Allow 2 Last Resort attempts = 3 total tries
        
        while last_resort_attempts <= max_last_resort_attempts:  # ← NEU!
            # Existing code...
```

### 2. Last Resort mit Counter

```python
            if not untried_combinations:
                if alternate_streams and len(self.tried_combinations) > 0:
                    logger.warning(f"All combinations tried")

                # LAST RESORT with limit
                if (ConfigHelper.stream_cooldown_enabled()
                        and hasattr(self.buffer, 'redis_client')
                        and self.buffer.redis_client
                        and alternate_streams
                        and last_resort_attempts < max_last_resort_attempts):  # ← NEU!
                    
                    # Clear all cooldowns
                    cooldown_pattern = f"live:channel:{self.channel_id}:cooldown:*"
                    deleted = redis_scan_delete(cooldown_pattern)
                    
                    if deleted > 0:
                        last_resort_attempts += 1  # ← NEU!
                        logger.info(
                            f"[COOLDOWN] Last resort attempt {last_resort_attempts}/{max_last_resort_attempts}: "
                            f"cleared {deleted} cooldown(s) - retrying all combinations"
                        )
                        self.tried_combinations.clear()
                        untried_combinations = alternate_streams
                        continue  # ← NEU! Zurück zum Anfang der while-Loop

                # No Last Resort possible or max attempts reached
                if last_resort_attempts >= max_last_resort_attempts:  # ← NEU!
                    logger.warning(
                        f"[COOLDOWN] Max Last Resort attempts ({max_last_resort_attempts}) "
                        f"reached - giving up"
                    )
                return False

            # Try combinations (existing code)
            for next_stream in untried_combinations:
                # ... existing code ...
                if success:
                    return True  # ← Verlässt die while-Loop

            # End of while loop - should not reach here
            logger.error("Unexpect end of while loop")
            return False
```

### 3. Loop-Ende anpassen

Die `for next_stream in untried_combinations` Loop ist jetzt INNERHALB der `while last_resort_attempts` Loop.

Wenn eine Kombination erfolgreich ist → `return True` → verlässt die gesamte Funktion.
Wenn alle Kombinationen fehlschlagen → zurück zum Anfang der while-Loop → Last Resort oder gibt auf.

## Durchläufe erklärt

### Durchlauf 1 (Initial, last_resort_attempts=0)

```
while last_resort_attempts (0) <= max (2):  ← JA, continue
    Markiere current als fehlgeschlagen + Cooldown
    Get alternate_streams
    Filter tried_combinations
    Filter Cooldowns
    
    Profile 340 → Fehler
    Profile 341 → Fehler
    Profile 342 → Fehler
    
    untried_combinations = [] (leer)
    
    Last Resort möglich? (attempts 0 < max 2)  ← JA!
        last_resort_attempts = 1
        Clear all Cooldowns
        tried_combinations.clear()
        untried_combinations = all
        continue  ← Zurück zum Anfang
```

### Durchlauf 2 (Nach Last Resort #1, last_resort_attempts=1)

```
while last_resort_attempts (1) <= max (2):  ← JA, continue
    Get alternate_streams (alle wieder verfügbar)
    Filter tried_combinations (leer nach clear)
    Filter Cooldowns (gelöscht)
    
    Profile 340 → Fehler
    Profile 341 → Fehler
    Profile 342 → Fehler
    
    untried_combinations = [] (leer)
    
    Last Resort möglich? (attempts 1 < max 2)  ← JA!
        last_resort_attempts = 2
        Clear all Cooldowns
        tried_combinations.clear()
        untried_combinations = all
        continue  ← Zurück zum Anfang
```

### Durchlauf 3 (Nach Last Resort #2, last_resort_attempts=2)

```
while last_resort_attempts (2) <= max (2):  ← JA, continue (LETZTES MAL!)
    Get alternate_streams (alle wieder verfügbar)
    Filter tried_combinations (leer nach clear)
    Filter Cooldowns (gelöscht)
    
    Profile 340 → Fehler
    Profile 341 → Fehler
    Profile 342 → Fehler
    
    untried_combinations = [] (leer)
    
    Last Resort möglich? (attempts 2 < max 2)  ← NEIN! (2 ist NICHT < 2)
        logger.warning("Max Last Resort attempts (2) reached - giving up")
        return False  ← Gibt auf!
```

**Ergebnis:** Maximal 3 Durchläufe, dann gibt System auf → KEINE Endlosschleife!

## Logs

### Mit Counter (korrekt):

```bash
# Durchlauf 1
[INFO] Trying stream 708953/profile 340
[INFO] Trying stream 708953/profile 341
[INFO] Trying stream 708953/profile 342
[COOLDOWN] Last resort attempt 1/2: cleared 3 cooldown(s) - retrying all combinations

# Durchlauf 2
[INFO] Trying stream 708953/profile 340
[INFO] Trying stream 708953/profile 341
[INFO] Trying stream 708953/profile 342
[COOLDOWN] Last resort attempt 2/2: cleared 3 cooldown(s) - retrying all combinations

# Durchlauf 3
[INFO] Trying stream 708953/profile 340
[INFO] Trying stream 708953/profile 341
[INFO] Trying stream 708953/profile 342
[COOLDOWN] Max Last Resort attempts (2) reached - giving up
[ERROR] Tried 0 alternate stream+profile combinations but none were suitable
```

### Ohne Counter (BUG):

```bash
# Durchlauf 1
[INFO] Trying stream 708953/profile 340
[INFO] Trying stream 708953/profile 341
[INFO] Trying stream 708953/profile 342
[COOLDOWN] Last resort: cleared 3 cooldown(s) - retrying all combinations

# Durchlauf 2
[INFO] Trying stream 708953/profile 340
[INFO] Trying stream 708953/profile 341
[INFO] Trying stream 708953/profile 342
[COOLDOWN] Last resort: cleared 3 cooldown(s) - retrying all combinations

# Durchlauf 3
[INFO] Trying stream 708953/profile 340
[INFO] Trying stream 708953/profile 341
[INFO] Trying stream 708953/profile 342
[COOLDOWN] Last resort: cleared 3 cooldown(s) - retrying all combinations

# Durchlauf 4
... (UNENDLICH WEITER!) ...
```

## Zusammenfassung

✅ **Mit Counter:** Maximal 3 Durchläufe (1 initial + 2x Last Resort)  
❌ **Ohne Counter:** Unendliche Schleife möglich  

**Fix:** 
1. `while`-Loop um gesamte Logik
2. Counter für Last Resort Attempts
3. `continue` nach Last Resort statt neues `untried_combinations` assignment

**Wichtig:** Dieser Fix ist KRITISCH um Endlosschleifen zu verhindern!
