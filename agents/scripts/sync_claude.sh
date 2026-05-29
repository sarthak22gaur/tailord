#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd "$AGENTS_DIR/.." && pwd)"

source "$SCRIPT_DIR/_lib.sh"

[[ -f "$AGENTS_DIR/agentsync.conf" ]] && source "$AGENTS_DIR/agentsync.conf"
CLAUDE_MD_TARGET="${CLAUDE_MD_TARGET:-.claude/CLAUDE.md}"

SRC="$AGENTS_DIR/claude"
SKILLS_SRC="$AGENTS_DIR/skills"
TARGET="$WORKSPACE_ROOT/.claude"

mkdir -p "$TARGET/agents" "$TARGET/skills" "$TARGET/rules"

# Merge-safe: only prune/replace agentsync's own entries; preserve anything the
# user or another generator keeps in these shared dirs.
sync_dir_files "$SRC/agents" "$TARGET/agents"
sync_skill_dirs_verbatim "$SKILLS_SRC" "$TARGET/skills"

if [[ -d "$SRC/rules" ]]; then
    sync_dir_files "$SRC/rules" "$TARGET/rules"
fi

if [[ -f "$SRC/CLAUDE.md" ]]; then
    CLAUDE_MD_DEST="$WORKSPACE_ROOT/$CLAUDE_MD_TARGET"
    mkdir -p "$(dirname "$CLAUDE_MD_DEST")"
    cp -f "$SRC/CLAUDE.md" "$CLAUDE_MD_DEST"
fi

if [[ -f "$SRC/settings.json" ]]; then
    cp -f "$SRC/settings.json" "$TARGET/settings.json"
fi

echo "Synced .claude/"
