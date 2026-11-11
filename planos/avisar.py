#!/usr/bin/env python3
"""Manda o aviso da coleta de planos: push no ntfy e e-mail no Gmail, os dois com a planilha anexa.

Lê planos/_coleta/mudancas.json (gerado por historico.py).
- Primeira coleta: aviso de "base montada".
- Com mudança: título com o número de mudanças e as principais no texto.
- Sem mudança: push discreto de "robô ok" (sem e-mail), para saber que rodou.
- Falha em mais de 20% das páginas de uma operadora: aviso de atenção.
E-mail precisa do secret GMAIL_APP_PASSWORD; sem ele, só vai o push.
Uso: python planos/avisar.py [--teste]
"""
import json, os, smtplib, subprocess, sys
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from pathlib import Path

AQUI = Path(__file__).parent
sys.path.insert(0, str(AQUI))
from historico import agrupar  # noqa: E402

TOPICO = os.environ.get("NTFY_TOPIC", "")
EMAIL = "mmagalhaes2001@gmail.com"
XLSX = AQUI / "planos_operadoras.xlsx"
REPO = os.environ.get("GITHUB_REPOSITORY", "mmagalhaes2001/Monitor-dados")
LINK = "https://github.com/%s/raw/main/planos/planos_operadoras.xlsx" % REPO
BRT = timezone(timedelta(hours=-3))


def ntfy(titulo, msg, prioridade="default", tags="iphone", anexo=True):
    if not TOPICO:
        print("sem NTFY_TOPIC")
        return
    cab = ["-H", "Title: " + titulo, "-H", "Priority: " + prioridade, "-H", "Tags: " + tags, "-H", "Click: " + LINK]
    tok = os.environ.get("NTFY_TOKEN")
    if tok:
        cab += ["-H", "Authorization: Bearer " + tok]
    url = "https://ntfy.sh/" + TOPICO
    for _ in range(3):
        if anexo and XLSX.exists():
            cmd = ["curl", "-sSf", "-m", "60", "-T", str(XLSX), "-H", "Filename: " + XLSX.name,
                   "-H", "Message: " + msg.replace("\n", "\\n")[:3500]] + cab + [url]
        else:
            cmd = ["curl", "-sSf", "-m", "30", "--data-binary", msg[:3900]] + cab + [url]
        if subprocess.run(cmd, capture_output=True).returncode == 0:
            return
    print("falha no ntfy:", titulo)


def email(titulo, msg):
    senha = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not senha:
        print("sem GMAIL_APP_PASSWORD: e-mail não enviado")
        return
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = EMAIL, EMAIL, titulo
    m.set_content(msg + "\n\nPlanilha anexa (também em %s)\n" % LINK)
    if XLSX.exists():
        m.add_attachment(XLSX.read_bytes(), maintype="application",
                         subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=XLSX.name)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
            s.login(EMAIL, senha)
            s.send_message(m)
    except Exception as e:
        print("falha no e-mail:", str(e)[:150])


def main():
    teste = "--teste" in sys.argv
    r = json.loads((AQUI / "_coleta" / "mudancas.json").read_text(encoding="utf-8"))
    hoje = datetime.now(BRT).strftime("%d/%m")
    cobertura = "; ".join("%s %d/%d páginas" % (op, v["paginas_ok"], v["paginas"]) for op, v in sorted(r["operadoras"].items()))
    alertas = [op for op, v in r["operadoras"].items() if v["paginas"] and v["paginas_ok"] < 0.8 * v["paginas"]]
    linhas = agrupar(r["mudancas"])
    pre = "Teste - " if teste else ""

    if r["primeira_vez"]:
        titulo = "%sPlanos: base montada (%s)" % (pre, hoje)
        msg = "Primeira coleta: %d planos×praça vigentes.\nCobertura: %s" % (r["n_vigentes"], cobertura)
        ntfy(titulo, msg, tags="white_check_mark")
        email(titulo, msg)
    elif linhas:
        titulo = "%sPlanos: %d mudança%s (%s)" % (pre, len(linhas), "s" if len(linhas) > 1 else "", hoje)
        msg = "\n".join(linhas[:25]) + ("\n… e mais %d (ver aba Mudanças)" % (len(linhas) - 25) if len(linhas) > 25 else "")
        msg += "\n\nCobertura: %s" % cobertura
        ntfy(titulo, msg, prioridade="high", tags="rotating_light")
        email(titulo, msg)
    else:
        titulo = "%sPlanos: sem mudança (%s)" % (pre, hoje)
        ntfy(titulo, "Robô ok. Cobertura: %s" % cobertura, prioridade="low", tags="ok", anexo=False)
        if teste:
            email(titulo, "Robô ok. Cobertura: %s" % cobertura)
    if alertas:
        falhas = "\n".join("%s: %s" % (op, ", ".join(r["operadoras"][op]["falhas"][:15])) for op in alertas)
        ntfy("%sPlanos: coleta incompleta (%s)" % (pre, ", ".join(alertas)),
             "Mais de 20%% das páginas falharam. Pode ser site fora do ar, bloqueio ou mudança de layout.\n" + falhas,
             prioridade="high", tags="warning", anexo=False)
    print(titulo)
    print("\n".join(linhas[:40]))


if __name__ == "__main__":
    main()
