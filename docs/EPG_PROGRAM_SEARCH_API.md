# EPG Program Search API

## Overview

The EPG Program Search API provides powerful filtering and search capabilities for EPG (Electronic Program Guide) program data. It supports complex text queries with AND/OR operators, parenthetical grouping, regex patterns, time-based filtering, and channel/stream matching.

**Endpoint:** `GET /api/epg/programs/search/`

**Authentication:** Required (JWT Bearer token)

---

## Query Parameters

### Text Search Parameters

#### **`title`** (string, optional)
Search program titles with support for:
- Simple terms: `title=football`
- AND operator: `title=premier AND league`
- OR operator: `title=Newcastle OR Villa`
- Nested groups with parentheses: `title=(Newcastle OR NEW) AND (Villa OR AST)`
- Default behavior: Space-separated terms use AND

**Examples:**
```
title=sports
title=premier AND league
title=Newcastle OR Villa
title=(Newcastle OR NEW) AND (Villa OR AST)
```

#### **`title_regex`** (boolean, optional)
When `true`, interprets the `title` parameter as a case-insensitive regex pattern.

**Examples:**
```
title=^The&title_regex=true          # Programs starting with "The"
title=\d{4}&title_regex=true         # Programs with 4-digit years
title=\b(United|City)\b&title_regex=true  # Match "United" or "City" as whole words
```

#### **`title_whole_words`** (boolean, optional)
When `true`, matches only whole words. Prevents "NEW" from matching "News" or "Newcastle".

**Examples:**
```
title=NEW&title_whole_words=true     # Matches "NEW" but not "News" or "Newsletter"
```

#### **`description`** (string, optional)
Search program descriptions. Supports the same features as `title`:
- AND/OR operators
- Parenthetical grouping
- Works with `description_regex` and `description_whole_words`

#### **`description_regex`** (boolean, optional)
When `true`, interprets `description` as a case-insensitive regex pattern.

#### **`description_whole_words`** (boolean, optional)
When `true`, matches only whole words in descriptions.

---

### Time Filtering Parameters

#### **`airing_at`** (ISO 8601 datetime, optional)
Find programs airing at a specific moment in time. Matches programs where:
```
start_time <= airing_at < end_time
```

**Example:**
```
airing_at=2026-02-14T20:00:00Z
```

#### **`start_after`** (ISO 8601 datetime, optional)
Programs starting at or after this time.

**Example:**
```
start_after=2026-02-14T18:00:00Z
```

#### **`start_before`** (ISO 8601 datetime, optional)
Programs starting at or before this time.

#### **`end_after`** (ISO 8601 datetime, optional)
Programs ending at or after this time.

#### **`end_before`** (ISO 8601 datetime, optional)
Programs ending at or before this time.

**Combined time range example:**
```
start_after=2026-02-14T19:00:00Z&start_before=2026-02-14T22:00:00Z
```

---

### Channel & Stream Filtering

#### **`channel`** (string, optional)
Filter by channel name (case-insensitive substring match).

**Example:**
```
channel=BBC One
```

#### **`channel_id`** (integer, optional)
Filter by exact channel ID.

**Example:**
```
channel_id=123
```

#### **`stream`** (string, optional)
Filter by stream name (case-insensitive substring match).

**Example:**
```
stream=Sky Sports
```

#### **`group`** (string, optional)
Filter by channel group name OR stream group name (case-insensitive substring match).

**Example:**
```
group=Sports
```

#### **`epg_source`** (integer, optional)
Filter by EPG source ID.

**Example:**
```
epg_source=5
```

---

### Response Customization

#### **`fields`** (string, optional)
Comma-separated list of fields to include in response. Reduces payload size for specific use cases.

**Available fields:**
- `id`, `title`, `sub_title`, `description`
- `start_time`, `end_time`, `tvg_id`, `custom_properties`
- `epg_source`, `epg_name`, `epg_icon_url`
- `channels`, `streams`

**Example:**
```
fields=title,start_time,end_time,channels
```

---

### Pagination Parameters

#### **`page`** (integer, optional, default: 1)
Page number for paginated results.

#### **`page_size`** (integer, optional, default: 50, max: 500)
Number of results per page.

**Example:**
```
page=2&page_size=100
```

---

## Response Format

### Standard Response (with pagination)

```json
{
  "count": 345,
  "next": "http://example.com/api/epg/programs/search/?page=2&...",
  "previous": null,
  "results": [
    {
      "id": 21382804,
      "title": "Premier League: Newcastle vs Aston Villa",
      "sub_title": "Match Week 25",
      "description": "LIVE coverage from St James' Park",
      "start_time": "2026-02-14T20:00:00Z",
      "end_time": "2026-02-14T22:00:00Z",
      "tvg_id": "skysportspremierleague.uk",
      "custom_properties": {"category": "Sports"},
      "epg_source": "Sky EPG UK",
      "epg_name": "Sky Sports Premier League",
      "epg_icon_url": "https://example.com/icon.png",
      "channels": [
        {
          "id": 14419,
          "name": "Sky Sports Premier League",
          "channel_number": 401.0,
          "channel_group": "UK | Sky Sports",
          "tvg_id": "skysportspremierleague.uk"
        }
      ],
      "streams": [
        {
          "id": 300,
          "name": "Sky Sports PL HD",
          "channel_group": "UK | Sports",
          "tvg_id": "SkySportsPL.uk",
          "m3u_account": "my_provider"
        }
      ]
    }
  ]
}
```

### With Field Selection

Request: `?fields=title,start_time,end_time`

```json
{
  "count": 345,
  "next": "...",
  "previous": null,
  "results": [
    {
      "title": "Premier League: Newcastle vs Aston Villa",
      "start_time": "2026-02-14T20:00:00Z",
      "end_time": "2026-02-14T22:00:00Z"
    }
  ]
}
```

---

## Usage Examples

### Example 1: Find football matches airing now
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:9191/api/epg/programs/search/?title=football&airing_at=2026-02-14T20:00:00Z"
```

### Example 2: Complex team search with abbreviations
Find programs mentioning either full names or abbreviations:
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:9191/api/epg/programs/search/?title=(Newcastle%20OR%20NEW)%20AND%20(Villa%20OR%20AST)&airing_at=2026-02-14T20:00:00Z"
```

### Example 3: Whole word matching to avoid false positives
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:9191/api/epg/programs/search/?title=NEW&title_whole_words=true&airing_at=2026-02-14T20:00:00Z"
```
This matches "NEW" but not "News", "Newcastle", or "Newsletter".

### Example 4: Regex pattern for advanced matching
Find programs starting with "Premier" or "Champions":
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:9191/api/epg/programs/search/?title=^(Premier%7CChampions)&title_regex=true"
```

### Example 5: Time window search on specific channel
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:9191/api/epg/programs/search/?channel=BBC%20One&start_after=2026-02-14T18:00:00Z&start_before=2026-02-14T23:00:00Z"
```

### Example 6: Minimal response with field selection
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:9191/api/epg/programs/search/?title=sports&fields=title,start_time,end_time&page_size=10"
```

### Example 7: Find programs by stream group
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:9191/api/epg/programs/search/?group=Sports&airing_at=2026-02-14T20:00:00Z"
```

### Example 8: Find all news programs in next 2 hours
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:9191/api/epg/programs/search/?title=news&start_after=2026-02-14T20:00:00Z&start_before=2026-02-14T22:00:00Z"
```

---

## Text Query Syntax

### Operators

- **AND**: Both terms must be present
  - Example: `premier AND league`
  
- **OR**: Either term must be present
  - Example: `Newcastle OR Villa`

- **Parentheses**: Group operations for complex logic
  - Example: `(A OR B) AND (C OR D)`

### Operator Precedence

Left-to-right evaluation with parentheses for grouping:
```
A AND B OR C         → Evaluated as: (A AND B) OR C
(A OR B) AND C       → A or B must match, AND C must match
A AND (B OR C)       → A must match, AND either B or C must match
```

### Default Behavior

Space-separated terms without explicit operators default to AND:
```
football premier league    → football AND premier AND league
```

---

## Performance Considerations

1. **Text searches** use database `LIKE` queries (or regex). For large datasets, consider:
   - Using more specific search terms
   - Combining with time filters to reduce result set
   - Using field selection to reduce response size

2. **Pagination**: Default page size is 50, max is 500. For large result sets, use pagination rather than increasing page_size to max.

3. **Regex searches** are more expensive than standard text searches. Use only when necessary.

4. **Prefetching**: The endpoint automatically prefetches related channels, streams, and groups to avoid N+1 queries.

5. **Indexes**: The following fields are indexed for fast queries:
   - `ProgramData.start_time`, `end_time`
   - `EPGData.tvg_id`
   - `Channel.channel_number`

---

## Error Handling

### Authentication Required
```json
{
  "detail": "Authentication credentials were not provided."
}
```
**Status:** 401 Unauthorized

### Invalid datetime format
Invalid ISO 8601 datetime values are silently ignored (filter not applied).

### Invalid regex pattern
If `title_regex=true` and pattern is invalid, the query may fail at the database level. Ensure regex patterns are valid.

---

## Integration Notes

### Frontend Integration

```javascript
// Example using fetch API
async function searchPrograms(query) {
  const token = localStorage.getItem('accessToken');
  const params = new URLSearchParams(query);
  
  const response = await fetch(
    `/api/epg/programs/search/?${params}`,
    {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Accept': 'application/json'
      }
    }
  );
  
  return await response.json();
}

// Usage
const results = await searchPrograms({
  title: '(Newcastle OR NEW) AND (Villa OR AST)',
  airing_at: new Date().toISOString(),
  page_size: 20
});
```

### Automation & Scripts

```python
import requests
from datetime import datetime

# Get token
response = requests.post('http://localhost:9191/api/accounts/token/', 
    json={'username': 'user', 'password': 'pass'})
token = response.json()['access']

# Search programs
headers = {'Authorization': f'Bearer {token}'}
params = {
    'title': 'football',
    'airing_at': datetime.utcnow().isoformat() + 'Z',
    'page_size': 50
}

response = requests.get(
    'http://localhost:9191/api/epg/programs/search/',
    headers=headers,
    params=params
)

programs = response.json()
print(f"Found {programs['count']} matching programs")
```

---

## API Versioning

This endpoint was introduced in **version 1.0** and follows semantic versioning. Breaking changes will be announced with major version increments.

---

## Related Endpoints

- `GET /api/epg/grid/` - Get EPG grid view (24-hour window)
- `POST /api/epg/current-programs/` - Get currently airing programs for specific channels
- `GET /api/epg/programs/` - List all programs (CRUD endpoint)
- `GET /api/epg/sources/` - Manage EPG sources

---

## Support & Feedback

For issues, feature requests, or questions about this API, please file an issue on the GitHub repository or consult the project documentation.
