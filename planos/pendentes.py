#!/usr/bin/env python3
"""O que falta coletar hoje (usado pelo agendamento para repetir só o que falhou).

Esperado por operadora = páginas (UF × página) lidas com sucesso em algum dia dos últimos 7.
Lido hoje = páginas com ok=sim em qualquer rodada de hoje.
Saída (uma linha por operadora pendente):  vivo SP,RJ,BA
Sem saída = nada pendente. Sem coleta hoje = "todas".
Uma operadora com até 2 páginas faltando não é repetida (falha isolada; entra na coleta de amanhã).
"""
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG = Path(__file__).parent / "dados" / "coletas.csv"
OPS = {"Vivo": "vivo", "Claro": "claro", "TIM": "tim", "NuCel": "nucel"}
TOLERANCIA = 2

hoje = datetime.now(timezone(timedelta(hours=-3))).strftime("%Y-%m-%d")
ini = (datetime.strptime(hoje, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
with open(LOG, encoding="utf-8-sig", newline="") as f:
    log = list(csv.DictReader(f))
if not any(r["data"] == hoje for r in log):
    print("todas")
    raise SystemExit
esperado, lido = {}, {}
for r in log:
    k = (r["uf"], r["pagina"])
    if r["ok"] == "sim" and ini <= r["data"] < hoje:
        esperado.setdefault(r["operadora"], set()).add(k)
    if r["ok"] == "sim" and r["data"] == hoje:
        lido.setdefault(r["operadora"], set()).add(k)
for op, esp in esperado.items():
    falta = esp - lido.get(op, set())
    if len(falta) > TOLERANCIA and op in OPS:
        print(OPS[op], ",".join(sorted({uf for uf, _ in falta})))
