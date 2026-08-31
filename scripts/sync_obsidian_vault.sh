#!/bin/bash
# sync_obsidian_vault.sh - Sincronizacion bidireccional robusta de la boveda
set -uo pipefail

VAULT_DIR="$HOME/.hermes/skills/conocimiento-sif/vault"
[ -d "$VAULT_DIR/.git" ] || { echo "ERROR: boveda no es repo git"; exit 1; }
cd "$VAULT_DIR"

git config --global --add safe.directory "$VAULT_DIR" 2>/dev/null || true
git config pull.rebase false 2>/dev/null || true

MSG=""

# 1. Commit de cambios locales (conclusiones de Hermes)
if [ -n "$(git status --porcelain)" ]; then
  git add -A >/dev/null 2>&1
  git commit -m "Hermes: conclusiones/actualizaciones $(date -u +%Y-%m-%dT%H:%M:%SZ)" >/dev/null 2>&1 || true
fi

# 2. Traer y fusionar remoto (merge, no ff-only; tolera divergencias)
BEFORE=$(git rev-parse HEAD 2>/dev/null || echo none)
if GIT_TERMINAL_PROMPT=0 git pull --no-edit --no-rebase origin main >/dev/null 2>&1; then
  AFTER=$(git rev-parse HEAD 2>/dev/null || echo none)
  if [ "$BEFORE" != "$AFTER" ]; then
    CHANGED=$(git diff --name-only "$BEFORE" "$AFTER" 2>/dev/null | grep -c "\.md$")
    [ "$CHANGED" -gt 0 ] && MSG="Boveda: $CHANGED archivo(s) .md actualizados desde Obsidian. "
  fi
else
  # Conflicto real de contenido: abortar merge y avisar (no romper el repo)
  git merge --abort >/dev/null 2>&1 || true
  echo "Boveda: conflicto de merge que requiere revision manual."
  exit 0
fi

# 3. Subir todo (commits locales + merge)
if [ -n "$(git log origin/main..HEAD 2>/dev/null)" ]; then
  if GIT_TERMINAL_PROMPT=0 git push origin main >/dev/null 2>&1; then
    MSG="${MSG}Cambios de Hermes subidos a GitHub."
  else
    echo "Boveda: fallo al hacer push (revisar credenciales)."
    exit 0
  fi
fi

[ -n "$MSG" ] && echo "$MSG"
exit 0
