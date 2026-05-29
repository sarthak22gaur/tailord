#!/bin/bash
# Shared helpers for the sync scripts. Sourced by every sync_*.sh.

# Name of the per-directory ownership manifest agentsync writes into each target
# dir it manages (e.g. .claude/skills/.agentsync-manifest). It lists, one per
# line, the entries (skill dir names / agent file names) agentsync owns there.
# Entries not in the manifest were placed by the user or another generator and
# are NEVER touched — this is what lets agentsync share a dir like .claude/skills/
# with another tool instead of clobbering it.
AGENTSYNC_MANIFEST=".agentsync-manifest"

# Delegator/Claude-only skills (frontmatter with agent: or context:) are not
# fanned out to other surfaces.
is_delegator_skill() {
    grep -Eq '^(agent|context): ' "$1"
}

# Ownership-scoped prune of a target directory. Removes only the entries
# agentsync owned on the previous sync (per the manifest) that are NOT in the
# new owned set — i.e. agentsync output the user has since removed from source.
# Foreign entries (never recorded in the manifest) are preserved. Then rewrites
# the manifest to the new owned set. Callers copy the owned entries in AFTER.
#
#   sync_prune_owned <target_dir> [owned_name ...]
sync_prune_owned() {
    local target="$1"; shift
    local -a owned=()
    [[ $# -gt 0 ]] && owned=("$@")
    local manifest="$target/$AGENTSYNC_MANIFEST"

    mkdir -p "$target"

    if [[ -f "$manifest" ]]; then
        local prev name keep
        while IFS= read -r prev; do
            [[ -n "$prev" ]] || continue
            keep=0
            for name in ${owned[@]+"${owned[@]}"}; do
                [[ "$name" == "$prev" ]] && { keep=1; break; }
            done
            [[ $keep -eq 0 ]] && rm -rf "${target:?}/$prev"
        done < "$manifest"
    fi

    if [[ ${#owned[@]} -gt 0 ]]; then
        printf '%s\n' "${owned[@]}" > "$manifest"
    else
        rm -f "$manifest"
    fi
}

# Merge-safe copy of regular files from a source dir into a target dir. Only
# agentsync-owned files are pruned; foreign files are preserved. $3 is an
# optional glob (default '*'); only regular files matching it are synced.
#
#   sync_dir_files <src_dir> <target_dir> [glob]
sync_dir_files() {
    local src="$1" target="$2" glob="${3:-*}"
    local -a names=()
    local f
    if [[ -d "$src" ]]; then
        for f in "$src"/$glob; do
            [[ -f "$f" ]] || continue
            names+=("$(basename "$f")")
        done
    fi
    sync_prune_owned "$target" ${names[@]+"${names[@]}"}
    for f in ${names[@]+"${names[@]}"}; do
        cp -f "$src/$f" "$target/$f"
    done
}

# Merge-safe verbatim copy of skill directories (each must contain SKILL.md)
# from a source dir into a target dir. Foreign skill dirs are preserved.
#
#   sync_skill_dirs_verbatim <skills_src> <target_dir>
sync_skill_dirs_verbatim() {
    local src="$1" target="$2"
    local -a names=()
    local d
    if [[ -d "$src" ]]; then
        for d in "$src"/*; do
            [[ -d "$d" && -f "$d/SKILL.md" ]] || continue
            names+=("$(basename "$d")")
        done
    fi
    sync_prune_owned "$target" ${names[@]+"${names[@]}"}
    for d in ${names[@]+"${names[@]}"}; do
        rm -rf "${target:?}/$d"
        cp -r "$src/$d" "$target/$d"
    done
}

# Strip Claude/OpenCode-only frontmatter keys so other tools can parse the skill.
normalize_skill() {
    awk '
        BEGIN { in_fm = 0; fm_count = 0 }
        /^---$/ {
            fm_count++
            if (fm_count == 1) { in_fm = 1; print; next }
            if (fm_count == 2) { in_fm = 0; print; next }
        }
        in_fm == 1 {
            if ($0 ~ /^(agent|context|disable-model-invocation|allowed-tools|argument-hint|model|effort|maxTurns|color|permission|permissionMode|tools|disallowedTools|hooks|mode|temperature|steps):/) next
            print
            next
        }
        { print }
    '
}
