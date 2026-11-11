#!/usr/bin/env python3
"""Envia um alerta por e-mail (Gmail SMTP) de mmagalhaes2001@gmail.com para ele mesmo.
Uso: python cvm44/enviar_email.py TITULO LINK MENSAGEM [ANEXO_PNG]
Precisa de GMAIL_APP_PASSWORD no ambiente (senha de app do Google). Sem ela, não faz nada.
"""
import os, smtplib, sys
from email.message import EmailMessage

DE = PARA = "mmagalhaes2001@gmail.com"


def main():
    senha = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if not senha:
        return
    titulo, link, msg = sys.argv[1], sys.argv[2], sys.argv[3]
    anexo = sys.argv[4] if len(sys.argv) > 4 else ""
    if titulo.startswith("Teste") or titulo.startswith("Robô CVM 44 ok"):
        return
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = DE, PARA, titulo
    m.set_content("%s\n\nAbrir: %s\n" % (msg, link))
    m.add_alternative("<p>%s</p><p><a href=\"%s\">Abrir documento na CVM</a></p>" % (msg.replace("\n", "<br>"), link), subtype="html")
    if anexo and os.path.exists(anexo):
        with open(anexo, "rb") as f:
            m.get_payload()[1].add_related(f.read(), "image", "png", cid="<grafico>")
            m.add_attachment(open(anexo, "rb").read(), maintype="image", subtype="png", filename=os.path.basename(anexo))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(DE, senha)
        s.send_message(m)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("falha no e-mail: %s" % str(e)[:120])
