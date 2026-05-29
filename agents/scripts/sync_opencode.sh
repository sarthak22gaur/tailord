#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd "$AGENTS_DIR/.." && pwd)"

source "$SCRIPT_DIR/_lib.sh"

SRC="$AGENTS_DIR/opencode"
SKILLS_SRC="$AGENTS_DIR/skills"
TARGET="$WORKSPACE_ROOT/.opencode"

mkdir -p "$TARGET/agents"

# Merge-safe: preserve foreign agents in the shared dir.
sync_dir_files "$SRC/agents" "$TARGET/agents"

# OpenCode reads skills from the shared .agents/skills/ location (populated by sync_codex.sh).
# If sync_codex didn't run, fall back to copying skills directly (merge-safe).
SHARED_SKILLS="$WORKSPACE_ROOT/.agents/skills"
if [[ ! -d "$SHARED_SKILLS" && -d "$SKILLS_SRC" ]]; then
    sync_skill_dirs_verbatim "$SKILLS_SRC" "$SHARED_SKILLS"
fi

if [[ -f "$AGENTS_DIR/AGENTS.md" ]]; then
    cp -f "$AGENTS_DIR/AGENTS.md" "$TARGET/AGENTS.md"
fi

echo "Synced .opencode/"
