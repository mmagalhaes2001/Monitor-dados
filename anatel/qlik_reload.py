"""
Data da última carga (reload) do app Qlik do painel de acessos da Anatel.

O painel (https://informacoes.anatel.gov.br/paineis/acessos/...) lê de um app Qlik Sense público em
dados.anatel.gov.br/qap. Quando a Anatel recarrega o app, o mês novo passa a valer em todas as
páginas do painel, mesmo que a página-índice ainda mostre "manutenção".

Uso: python anatel/qlik_reload.py  -> imprime JSON {"reload": "AAAA-MM-DDTHH:MM:SS.sssZ", "titulo": ...}
"""
import asyncio
import json
import os
import ssl
import sys
import time

import websockets

APP = "b00f5b60-c868-4b2e-b235-74ffc5c04a5a"


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
        lay = (await call(doc, "GetAppLayout", []))["qLayout"]
        return {"reload": lay.get("qLastReloadTime"), "titulo": lay.get("qTitle")}


if __name__ == "__main__":
    for t in range(3):
        try:
            print(json.dumps(asyncio.run(consultar()), ensure_ascii=False))
            sys.exit(0)
        except Exception as e:
            print(f"tentativa {t + 1} falhou: {e}", file=sys.stderr)
            time.sleep(20)
    sys.exit(1)
