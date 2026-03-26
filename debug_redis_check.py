#!/usr/bin/env python
import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
import django
django.setup()

from core.utils import RedisClient

r = RedisClient.get_client()
print(f"Client: {r}")
print(f"decode_responses: {r.connection_pool.connection_kwargs.get('decode_responses')}")

keys = list(r.scan_iter(match='ts_proxy:channel:*:metadata', count=100))
print(f"Found {len(keys)} metadata keys")
for k in keys[:3]:
    print(f"  Key: {k!r}")
    data = r.hgetall(k)
    field_names = list(data.keys())[:8]
    print(f"  Fields ({len(data)} total): {field_names}")
    state = data.get('state', 'MISSING')
    print(f"  state={state!r}")
