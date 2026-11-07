#!/usr/bin/env python3
"""Lista os formulários de negociação de administradores (art. 11 da Res. CVM 44,
categoria "Valores Mobiliários Negociados e Detidos") entregues pelas empresas de
cvm44/empresas.csv, consultando o sistema ENET da CVM.

Uso: python cvm44/checar.py [dias]   (padrão: últimos 45 dias)
Saída: JSON {"ok": bool, "docs": [...], "erro": str}
Cada doc: ticker, nome, tipo, ref (MM/AAAA), entrega (DD/MM/AAAA HH:MM), versao, protocolo, link
"""
import csv, html, json, re, sys, os, urllib.request
from datetime import date, timedelta

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = "https://www.rad.cvm.gov.br/ENETWeb/"
URL = BASE + "frmConsultaExternaCVM.aspx/ListarDocumentos"
CATEGORIA = "Valores Mobiliários Negociados e Detidos"


def empresas():
    with open(os.path.join(AQUI, "empresas.csv"), encoding="utf-8") as f:
        return [r for r in csv.DictReader(f, delimiter=";") if r.get("cod_cvm")]


def consultar(codigos, dias):
    hoje = date.today()
    ini = hoje - timedelta(days=dias)
    corpo = ("{ dataDe: '%s', dataAte: '%s', empresa: '%s', setorAtividade: '-1', "
             "categoriaEmissor: '-1', situacaoEmissor: '-1', tipoParticipante: '-1', "
             "dataReferencia: '', categoria: 'TODAS', periodo: '2', horaIni: '', horaFim: '', "
             "palavraChave:'', ultimaDtRef:'false', tipoEmpresa:'0', token: '', versaoCaptcha: ''}"
             % (ini.strftime("%d/%m/%Y"), hoje.strftime("%d/%m/%Y"), "," + ",".join(codigos)))
    req = urllib.request.Request(URL, data=corpo.encode("utf-8"), headers={
        "Content-Type": "application/json; charset=utf-8",
        "Referer": BASE + "frmConsultaExternaCVM.aspx",
        "User-Agent": "Mozilla/5.0",
    })
    with urllib.request.urlopen(req, timeout=90) as r:
        d = json.load(r)["d"]
    if d.get("temErro"):
        raise RuntimeError(d.get("msgErro") or "erro na consulta")
    if d.get("SolicitarCaptcha") == "S":
        raise RuntimeError("CVM pediu captcha")
    return d.get("dados", "")


def limpar(x):
    return re.sub(r"<[^>]+>", "", html.unescape(x)).strip()


def parsear(dados, por_codigo):
    docs = []
    for linha in dados.split("$&&"):
        c = linha.split("$&")
        if len(c) < 11 or limpar(c[2]) != CATEGORIA:
            continue
        cod = limpar(c[0]).lstrip("*")          # "02462-7"
        cod6 = cod.replace("-", "")            # "024627"
        emp = por_codigo.get(cod6)
        if not emp:
            continue
        prot = re.search(r"NumeroProtocoloEntrega=(\d+)", html.unescape(c[10]))
        docs.append({
            "ticker": emp["ticker"], "nome": emp["nome"],
            "tipo": limpar(c[3]), "ref": limpar(c[5])[-7:], "entrega": limpar(c[6])[-16:],
            "versao": limpar(c[8]), "protocolo": prot.group(1) if prot else "",
            "link": BASE + "frmExibirArquivoIPEExterno.aspx?NumeroProtocoloEntrega=" + prot.group(1) if prot else BASE + "frmConsultaExternaCVM.aspx",
        })
    docs.sort(key=lambda d: (d["entrega"][6:10], d["entrega"][3:5], d["entrega"][0:2], d["entrega"][11:]))
    return docs


def main():
    dias = int(sys.argv[1]) if len(sys.argv) > 1 else 45
    try:
        emps = empresas()
        por_codigo = {e["cod_cvm"]: e for e in emps}
        dados = consultar([e["cod_cvm"] for e in emps], dias)
        print(json.dumps({"ok": True, "docs": parsear(dados, por_codigo)}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "docs": [], "erro": str(e)[:200]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
