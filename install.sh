#!/usr/bin/env bash
set -euo pipefail

uuid=clausage@pedroelizalde01.github.com
target="${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/$uuid"
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

mkdir -p "$target"
install -m 0644 "$source_dir/extension.js" "$source_dir/usage.py" "$source_dir/metadata.json" "$target/"

echo "Installed $uuid"
echo "Reload GNOME Shell, then run: gnome-extensions enable $uuid"
