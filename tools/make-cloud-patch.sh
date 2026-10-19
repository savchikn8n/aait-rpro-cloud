#!/usr/bin/env bash
# Собирает патч «облачная модель» для уже установленного агента (на Mac/Linux, без Windows).
# Ключ берётся из переменной OPENROUTER_API_KEY (в историю терминала не попадёт, если вводить через read -s).
# Результат: dist/rpro-agent-cloud-patch.zip — внутри ключ, раздавать только своим.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${OPENROUTER_API_KEY:?задайте OPENROUTER_API_KEY}"
OUT=dist/cloud-patch; rm -rf dist; mkdir -p "$OUT/agent"
# код агента: как в installer/build.ps1 — без инструментов разработки
for f in agent/*.py; do
  case "$(basename "$f")" in tickhunt.py|probe.py|demo.py|kb_build.py|quickref_build.py) continue;; esac
  cp "$f" "$OUT/agent/"
done
python3 - <<PY
import json,os
json.dump({"RPRO_LLM":"openrouter","OPENROUTER_API_KEY":os.environ["OPENROUTER_API_KEY"]},
          open("$OUT/cloud-settings.json","w"),indent=2)
PY
cp tools/apply-cloud-patch.ps1 "$OUT/"
cat > "$OUT/Установить.cmd" <<'CMD'
@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0apply-cloud-patch.ps1"
pause
CMD
(cd dist && zip -qr rpro-agent-cloud-patch.zip cloud-patch && mv cloud-patch cloud-patch.d)
echo "Готово: $(pwd)/dist/rpro-agent-cloud-patch.zip"
