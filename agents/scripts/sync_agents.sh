#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd "$AGENTS_DIR/.." && pwd)"

echo "Syncing agent surfaces from $AGENTS_DIR"

if [[ -d "$AGENTS_DIR/claude" ]]; then
    "$SCRIPT_DIR/sync_claude.sh"
fi

if [[ -d "$AGENTS_DIR/codex" ]]; then
    "$SCRIPT_DIR/sync_codex.sh"
fi

if [[ -d "$AGENTS_DIR/opencode" ]]; then
    "$SCRIPT_DIR/sync_opencode.sh"
fi

if [[ -d "$AGENTS_DIR/github" ]]; then
    "$SCRIPT_DIR/sync_github.sh"
fi

if [[ -f "$AGENTS_DIR/AGENTS.md" ]]; then
    cp -f "$AGENTS_DIR/AGENTS.md" "$WORKSPACE_ROOT/AGENTS.md"
    echo "Wrote $WORKSPACE_ROOT/AGENTS.md"
fi

"$SCRIPT_DIR/apply_gitignore.sh"

echo "Sync complete."
