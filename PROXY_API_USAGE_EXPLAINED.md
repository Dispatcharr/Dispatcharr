# HTTP Proxy für API-Calls - Erklärung

## Wie funktioniert der Proxy?

### 1. Datenbank-Felder in M3UAccount

```python
class M3UAccount(models.Model):
    proxy = models.CharField(max_length=500, blank=True, null=True)
    proxy_for_api = models.BooleanField(default=False)
```

- **`proxy`**: Das HTTP-Proxy Feld (z.B. `http://proxy.example.com:8080`)
- **`proxy_for_api`**: Boolean Flag - aktiviert Proxy für API-Calls

### 2. Nutzung im Code

```python
def get_proxy_for_api(self):
    """Get proxy URL for API calls only if proxy_for_api is enabled."""
    if self.proxy and self.proxy.strip() and self.proxy_for_api:
        logger.info(f"M3UAccount {self.id}: Using proxy for API calls: {self.proxy}")
        return self.proxy  # ← Gibt den Wert aus dem "proxy" Feld zurück
    elif self.proxy and self.proxy.strip() and not self.proxy_for_api:
        logger.debug(f"M3UAccount {self.id}: Proxy configured but proxy_for_api is disabled")
    return None
```

### 3. Verwendung in XtreamCodes Client

```python
# In apps/m3u/tasks.py:
with XCClient(
    account.server_url,
    account.username,
    account.password,
    account.get_user_agent(),
    proxy=account.get_proxy_for_api()  # ← Hier wird der Proxy übergeben
) as xc_client:
    xc_client.get_live_categories()  # Nutzt den Proxy!
```

### 4. XCClient nutzt den Proxy

```python
# In core/xtream_codes.py:
def __init__(self, server_url, username, password, user_agent=None, proxy=None):
    self.session = requests.Session()
    
    # Configure proxy if provided
    if proxy:
        self.session.proxies = {'http': proxy, 'https': proxy}
        logger.info(f"XC Client using HTTP proxy: {proxy}")
```

---

## Zusammenfassung

### ✅ Was funktioniert

1. **Ein Feld für alles**: Das `proxy` Feld wird für BEIDE verwendet:
   - Streaming (FFmpeg `-http_proxy`)
   - API-Calls (requests.Session.proxies)

2. **Separater Toggle**: `proxy_for_api` Flag kontrolliert NUR API-Nutzung
   - `proxy_for_api = False` → Proxy nur für Streaming
   - `proxy_for_api = True` → Proxy für Streaming UND API

### 📋 Beispiel-Szenarien

#### Szenario 1: Proxy nur für Streaming
```
proxy = "http://proxy.example.com:8080"
proxy_for_api = False

Result:
- FFmpeg nutzt Proxy ✅
- API-Calls nutzen KEINEN Proxy ❌
```

#### Szenario 2: Proxy für alles
```
proxy = "http://proxy.example.com:8080"
proxy_for_api = True

Result:
- FFmpeg nutzt Proxy ✅
- API-Calls nutzen Proxy ✅
```

#### Szenario 3: Kein Proxy
```
proxy = ""
proxy_for_api = False/True (egal)

Result:
- FFmpeg nutzt KEINEN Proxy ❌
- API-Calls nutzen KEINEN Proxy ❌
```

---

## 🐛 Dein Problem

In deinen Logs sehe ich:
```
WARNING urllib3.connectionpool Retrying ... 'ReadTimeoutError("HTTPConnectionPool(host='204.52.191.254', port=80): Read timed out. (read timeout=60)")'
```

Das bedeutet:
1. ❌ API-Call geht DIREKT zum Provider (ohne Proxy)
2. ❌ Provider ist langsam/geblockt → Timeout nach 60 Sekunden

### 🔧 Lösung

**Option 1: Via UI** (Empfohlen)
1. Gehe zu M3U Account Settings
2. Setze "Use Proxy for API Calls" auf ✅
3. Speichern
4. Refresh Account

**Option 2: Via Django Admin**
```python
from apps.m3u.models import M3UAccount

account = M3UAccount.objects.get(id=235)  # Dein "Deltatest" Account
account.proxy_for_api = True
account.save()
```

**Option 3: Via SQL**
```sql
UPDATE m3u_m3uaccount 
SET proxy_for_api = TRUE 
WHERE id = 235;
```

---

## 📊 Überprüfung

Nach dem Aktivieren solltest du diese Logs sehen:

### ✅ Erfolgreich aktiviert
```
INFO M3UAccount 235 (Deltatest): Using proxy for API calls: http://your-proxy:8080
INFO XC Client using HTTP proxy: http://your-proxy:8080
```

### ⚠️ Nicht aktiviert
```
DEBUG M3UAccount 235: Proxy configured (http://your-proxy:8080) but proxy_for_api is disabled
```

### ❌ Kein Proxy konfiguriert
```
(keine Logs über Proxy)
```

---

## 🎯 Wichtig zu verstehen

**Es gibt NUR EIN Proxy-Feld!**

- Feld Name in DB: `proxy`
- Feld Name in UI: "HTTP Proxy"
- Verwendet für:
  - **Immer**: FFmpeg Streaming (`-http_proxy`)
  - **Optional**: API Calls (wenn `proxy_for_api = True`)

**Nicht verwechseln mit:**
- Es gibt KEIN separates "API Proxy" Feld
- Es gibt KEIN separates "Streaming Proxy" Feld
- Nur: **1 Proxy-Feld + 1 Toggle-Flag**

---

## 🔍 Debug-Commands

### Check aktuellen Status
```python
from apps.m3u.models import M3UAccount

account = M3UAccount.objects.get(id=235)
print(f"Proxy: {account.proxy}")
print(f"Proxy for API: {account.proxy_for_api}")
print(f"Get proxy for API: {account.get_proxy_for_api()}")
```

### Erwartete Ausgabe (wenn richtig konfiguriert)
```
Proxy: http://your-proxy:8080
Proxy for API: True
Get proxy for API: http://your-proxy:8080
```

### Erwartete Ausgabe (wenn nicht aktiviert)
```
Proxy: http://your-proxy:8080
Proxy for API: False
Get proxy for API: None  ← Deshalb nutzen API-Calls keinen Proxy!
```

---

## ✅ Nach dem Fix

Wenn du `proxy_for_api = True` setzt, werden die API-Timeouts verschwinden:

### Vorher (ohne Proxy)
```
WARNING urllib3.connectionpool Retrying (Retry(total=2...)) after connection broken by 'ReadTimeoutError...'
WARNING urllib3.connectionpool Retrying (Retry(total=1...)) after connection broken by 'ReadTimeoutError...'
```

### Nachher (mit Proxy)
```
INFO M3UAccount 235: Using proxy for API calls: http://your-proxy:8080
INFO XC Client using HTTP proxy: http://your-proxy:8080
INFO core.xtream_codes XC Authentication successful for user 2629ded543d6
INFO apps.m3u.tasks Getting live categories from XC server
✅ Keine Timeouts mehr!
```

---

**Kurz gesagt**: Setze `proxy_for_api = True` und der Proxy aus dem normalen HTTP-Proxy Feld wird auch für API-Calls genutzt! 🎉
