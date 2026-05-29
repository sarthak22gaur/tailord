#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd "$AGENTS_DIR/.." && pwd)"

source "$SCRIPT_DIR/_lib.sh"

SRC="$AGENTS_DIR/github"
SKILLS_SRC="$AGENTS_DIR/skills"
TARGET="$WORKSPACE_ROOT/.github"
SKILLS_TARGET="$TARGET/skills"

mkdir -p "$TARGET/agents" "$SKILLS_TARGET"

# Copilot agent profiles (.agent.md) are verbatim source — copied, never generated.
# Merge-safe: preserve foreign .agent.md profiles.
sync_dir_files "$SRC/agents" "$TARGET/agents" '*.agent.md'

# Shared skills → .github/skills/, with the same delegator skip and Claude-only-key
# normalization as Codex. Merge-safe: only prune/replace agentsync-owned skill dirs.
owned_skills=()
if [[ -d "$SKILLS_SRC" ]]; then
    for skill_dir in "$SKILLS_SRC"/*; do
        [[ -d "$skill_dir" && -f "$skill_dir/SKILL.md" ]] || continue
        is_delegator_skill "$skill_dir/SKILL.md" && continue
        owned_skills+=("$(basename "$skill_dir")")
    done
fi
sync_prune_owned "$SKILLS_TARGET" ${owned_skills[@]+"${owned_skills[@]}"}

if [[ -d "$SKILLS_SRC" ]]; then
    for skill_dir in "$SKILLS_SRC"/*; do
        [[ -d "$skill_dir" && -f "$skill_dir/SKILL.md" ]] || continue
        if is_delegator_skill "$skill_dir/SKILL.md"; then
            continue
        fi
        name="$(basename "$skill_dir")"
        rm -rf "${SKILLS_TARGET:?}/$name"
        mkdir -p "$SKILLS_TARGET/$name"
        for entry in "$skill_dir"/*; do
            base="$(basename "$entry")"
            [[ "$base" == "SKILL.md" ]] && continue
            cp -R "$entry" "$SKILLS_TARGET/$name/"
        done
        normalize_skill < "$skill_dir/SKILL.md" > "$SKILLS_TARGET/$name/SKILL.md"
    done
fi

echo "Synced .github/"
