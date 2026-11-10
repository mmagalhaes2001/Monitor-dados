#!/usr/bin/env bash
# Segundo canal de aviso: cria uma issue no GitHub (gera e-mail do GitHub). Uso: issue.sh TITULO LINK MENSAGEM
t="$1"; link="$2"; msg="$3"
case "$t" in Teste*|"Robô CVM 44 ok"*) exit 0;; esac
body="$(printf '%s\n\nAbrir: %s\n' "$msg" "$link")"
gh issue create --repo "$GITHUB_REPOSITORY" --title "$t" --body "$body" --label cvm44 >/dev/null 2>&1 \
  || gh issue create --repo "$GITHUB_REPOSITORY" --title "$t" --body "$body" >/dev/null 2>&1 \
  || echo "falha na issue: $t"
