#!/usr/bin/env python3
"""Mescla o estado local (/tmp/cvm44_local.json) no estado do repositório (estado/cvm44.json)."""
import json, os, sys
local, repo = sys.argv[1], sys.argv[2]
a = json.load(open(local, encoding="utf-8"))
b = json.load(open(repo, encoding="utf-8")) if os.path.exists(repo) else {"vistos": {}}
b.setdefault("vistos", {}).update(a.get("vistos", {}))
json.dump(b, open(repo, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
