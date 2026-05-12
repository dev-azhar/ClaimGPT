#!/usr/bin/env bash
# Render docs/architecture.md Mermaid blocks to crisp SVG + 2x-DPI PNG
# in docs/img/. Re-run after editing the Mermaid sources.
#
# Requires Node 18+ and an installed Chrome (see docs/architecture.md).
#
# Usage:  bash infra/scripts/render_diagrams.sh
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

OUT_DIR="docs/img"
TMP_DIR="tmp/mermaid"
mkdir -p "$OUT_DIR" "$TMP_DIR"

# 1. Install mermaid-cli once into tmp/mermaid (kept out of git via .gitignore)
if [[ ! -x "$TMP_DIR/node_modules/.bin/mmdc" ]]; then
  echo "📦 Installing @mermaid-js/mermaid-cli into $TMP_DIR ..."
  npm install --no-save --prefix "$TMP_DIR" @mermaid-js/mermaid-cli@10.9.1 >/dev/null
fi

# 2. Puppeteer config — use system Chrome to avoid downloading another copy.
PUPPETEER_CFG="$TMP_DIR/puppeteer.json"
if [[ ! -f "$PUPPETEER_CFG" ]]; then
  CHROME=""
  for c in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/usr/bin/google-chrome" \
    "/usr/bin/chromium" \
    "/usr/bin/chromium-browser"; do
    [[ -x "$c" ]] && CHROME="$c" && break
  done
  if [[ -n "$CHROME" ]]; then
    cat > "$PUPPETEER_CFG" <<EOF
{ "args": ["--no-sandbox"], "executablePath": "$CHROME" }
EOF
  else
    echo '{ "args": ["--no-sandbox"] }' > "$PUPPETEER_CFG"
  fi
fi

MMDC="$TMP_DIR/node_modules/.bin/mmdc"

# 3. Extract every ```mermaid``` fenced block from docs/architecture.md
python3 - <<'PY'
import re, pathlib
src = pathlib.Path("docs/architecture.md").read_text()
for i, b in enumerate(re.findall(r"```mermaid\n(.*?)\n```", src, re.S), 1):
    pathlib.Path(f"tmp/mermaid/diagram_{i}.mmd").write_text(b + "\n")
PY

# 4. Map each block to its asset name (component first, sequence second).
declare -a NAMES=("component_diagram" "claims_processing_pipeline")

i=1
for name in "${NAMES[@]}"; do
  src="$TMP_DIR/diagram_${i}.mmd"
  [[ -f "$src" ]] || { echo "⚠️  missing $src — skipping $name"; i=$((i+1)); continue; }
  echo "🎨 rendering $name (svg + 2x png)"
  "$MMDC" -i "$src" -o "$OUT_DIR/$name.svg" -t neutral -b white --width 2400 -p "$PUPPETEER_CFG" >/dev/null
  "$MMDC" -i "$src" -o "$OUT_DIR/$name.png" -t neutral -b white --width 3840 --scale 2 -p "$PUPPETEER_CFG" >/dev/null
  i=$((i+1))
done

echo "✅ Rendered $((i-1)) diagrams to $OUT_DIR/"
ls -la "$OUT_DIR/"
