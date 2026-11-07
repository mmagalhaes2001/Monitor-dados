#!/usr/bin/env python3
"""Imprime os pushes do JSON do processar.py, um por linha, campos separados por \x1f."""
import json, sys
for p in json.load(open(sys.argv[1])).get("pushes", []):
    print("\x1f".join([p["titulo"], p["prio"], p["tags"], p["click"], p["msg"].replace("\n", " ")]))
