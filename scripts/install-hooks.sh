#!/usr/bin/env bash
# Install the tracked git hooks into this clone's .git/hooks/ directory.
# Run once per fresh clone (laptop, desktop, CI, etc.).
#
# Usage:  bash scripts/install-hooks.sh
#
# Why a script and not just `core.hooksPath`?  Setting core.hooksPath to a
# tracked directory works, but means every hook in that directory becomes
# active automatically — including any a future contributor adds.  The
# explicit copy keeps the install step visible and per-machine opt-in.

set -euo pipefail

# Resolve repo root regardless of where the script is invoked from.
repo_root=$(git rev-parse --show-toplevel 2>/dev/null || {
    echo "Not inside a git repository." >&2
    exit 1
})

src_dir="$repo_root/scripts/hooks"
dst_dir="$repo_root/.git/hooks"

if [ ! -d "$src_dir" ]; then
    echo "Source hooks directory missing: $src_dir" >&2
    exit 1
fi

mkdir -p "$dst_dir"

installed=0
for src in "$src_dir"/*; do
    [ -f "$src" ] || continue
    name=$(basename "$src")
    dst="$dst_dir/$name"
    cp "$src" "$dst"
    chmod +x "$dst"
    echo "Installed: .git/hooks/$name"
    installed=$((installed + 1))
done

if [ "$installed" -eq 0 ]; then
    echo "No hooks found in $src_dir." >&2
    exit 1
fi

echo "Done.  $installed hook(s) installed."
