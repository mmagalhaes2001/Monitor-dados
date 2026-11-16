"""
Acessos da Nucel (NUCOMMERCE LTDA, CNPJ 42.508.683/0001-32), credenciada de rede virtual na Claro.

A base aberta de acessos (zip) soma a Nucel dentro da Claro. O número separado só existe no painel
de telefonia móvel da Anatel (https://informacoes.anatel.gov.br/paineis/acessos/telefonia-movel),
tabela "Assinaturas das empresas credenciadas". O painel é um app Qlik Sense público (sem login);
este script consulta o mesmo app pelo websocket do Qlik, sem navegador.

Uso:
  python anatel/nucel.py                 # imprime JSON com a série mensal
  python anatel/nucel.py --csv saida.csv # também grava a série em CSV
"""
import argparse
import asyncio
import csv
import json
import os
import ssl
import sys
import time

import websockets

APP = "b00f5b60-c868-4b2e-b235-74ffc5c04a5a"  # app Qlik do painel "Acessos - Telefonia Móvel"
PAINEL = "https://informacoes.anatel.gov.br/paineis/acessos/telefonia-movel"
CNPJ = "42508683000132"

F = f"[CNPJ Credenciada]={{'{CNPJ}'}}"
MEDIDAS = [
    ("nucel", f"Sum({{<{F}>}}[Acessos Credenciadas])"),
    ("nucel_pos", f"Sum({{<{F},[Modalidade de Cobrança]={{'Pós-pago'}}>}}[Acessos Credenciadas])"),
    ("nucel_pre", f"Sum({{<{F},[Modalidade de Cobrança]={{'Pré-pago'}}>}}[Acessos Credenciadas])"),
    ("nucel_5g", f"Sum({{<{F},[Tecnologia Geração]={{'5G'}}>}}[Acessos Credenciadas])"),
    ("nucel_4g", f"Sum({{<{F},[Tecnologia Geração]={{'4G'}}>}}[Acessos Credenciadas])"),
    ("claro_credenciadas", "Sum({<Empresa={'CLARO'}>}[Acessos Credenciadas])"),
    ("todas_credenciadas", "Sum([Acessos Credenciadas])"),
]


async def consultar():
    url = (f"wss://dados.anatel.gov.br/qap/app/{APP}?reloadUri=https%3A%2F%2Finformacoes.anatel.gov.br"
           f"%2Fpaineis%2Facessos%2Ftelefonia-movel&identity=robo{int(time.time())}")
    ctx = ssl.create_default_context(cafile=os.environ.get("SSL_CERT_FILE"))
    hdr = {"Origin": "https://informacoes.anatel.gov.br", "User-Agent": "Mozilla/5.0"}
    async with websockets.connect(url, additional_headers=hdr, ssl=ctx, max_size=50_000_000,
                                  open_timeout=60) as ws:
        n = 0

        async def call(handle, method, params):
            nonlocal n
            n += 1
            meu = n
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": meu, "handle": handle,
                                      "method": method, "params": params}))
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), 120))
                if m.get("id") == meu:
                    if "error" in m:
                        raise RuntimeError(f"{method}: {m['error']}")
                    return m["result"]

        doc = (await call(-1, "OpenDoc", [APP]))["qReturn"]["qHandle"]
        hc = {"qDimensions": [{"qDef": {"qFieldDefs": ["Data"]}}],
              "qMeasures": [{"qDef": {"qDef": d}} for _, d in MEDIDAS],
              "qSuppressZero": False,
              "qInitialDataFetch": [{"qTop": 0, "qLeft": 0, "qWidth": len(MEDIDAS) + 1, "qHeight": 1000}]}
        obj = (await call(doc, "CreateSessionObject", [{"qInfo": {"qType": "HC"}, "qHyperCubeDef": hc}]))
        lay = (await call(obj["qReturn"]["qHandle"], "GetLayout", []))["qLayout"]["qHyperCube"]
        linhas = []
        for r in lay["qDataPages"][0]["qMatrix"]:
            mm, aaaa = r[0]["qText"].split("-")  # "09-2026"
            vals = {k: (int(c["qNum"]) if isinstance(c["qNum"], (int, float)) else 0)
                    for (k, _), c in zip(MEDIDAS, r[1:])}
            linhas.append({"mes": f"{aaaa}-{mm}", **vals})
    linhas.sort(key=lambda x: x["mes"])
    # Só meses com dado de credenciadas publicado
    linhas = [x for x in linhas if x["todas_credenciadas"] > 0]
    return linhas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    a = ap.parse_args()
    serie = None
    for t in range(3):
        try:
            serie = asyncio.run(consultar())
            break
        except Exception as e:  # painel instável: tenta de novo
            print(f"tentativa {t + 1} falhou: {e}", file=sys.stderr)
            time.sleep(20)
    if not serie:
        sys.exit(1)
    ult = serie[-1]
    ant = serie[-2] if len(serie) > 1 else None
    res = {
        "mes": ult["mes"],
        "nucel": ult["nucel"],
        "adicoes_mm": ult["nucel"] - ant["nucel"] if ant else None,
        "nucel_5g": ult["nucel_5g"],
        "share_nas_credenciadas_claro": round(ult["nucel"] / ult["claro_credenciadas"], 4) if ult["claro_credenciadas"] else None,
        "fonte": PAINEL,
        "serie": serie,
    }
    if a.csv:
        os.makedirs(os.path.dirname(a.csv) or ".", exist_ok=True)
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(serie[0].keys()), delimiter=";")
            w.writeheader()
            w.writerows(serie)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
