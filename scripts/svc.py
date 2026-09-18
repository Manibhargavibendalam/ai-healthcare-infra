#!/usr/bin/env python3
"""Operator exec helper — run INSIDE a service container, e.g.:
  docker compose exec -T ehr-mock python /scripts/svc.py 8002 POST /mode '{"mode":"slow"}'
  docker compose exec -T ai python /scripts/svc.py 8001 GET /health
Proves internal connectivity WITHOUT publishing ports. The SHELL channel
(docker exec, like kubectl exec) is the access path — audited, no network
exposure, gone at the networking boundary. Mounted read-only via compose.
"""
import sys
import urllib.request

port, method, path = sys.argv[1], sys.argv[2].upper(), sys.argv[3]
data = sys.argv[4].encode() if len(sys.argv) > 4 else None
req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                             headers={"Content-Type": "application/json"},
                             method=method)
try:
    resp = urllib.request.urlopen(req, timeout=10)
    print(resp.status)
    print(resp.read().decode())
except Exception as e:  # HTTPError etc: print code + body, exit nonzero
    body = ""
    try:
        body = e.read().decode()  # noqa: F841 - shown below
    except Exception:
        pass
    print(getattr(e, "code", "ERR"))
    print(body or e)
    sys.exit(1)
