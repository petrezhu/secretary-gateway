#!/usr/bin/env bash
# Install secretary-gateway plugin into Hermes.
#
# Usage:
#   ./install.sh              # install to ~/.hermes/plugins/ (global)
#   ./install.sh --profile main  # install to ~/.hermes/profiles/main/plugins/
#   ./install.sh --symlink    # symlink instead of copy (for development)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_NAME="secretary-gateway"
GLOBAL_DIR="$HOME/.hermes/plugins/$PLUGIN_NAME"
PROFILE=""
USE_SYMLINK=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)
            PROFILE="$2"
            shift 2
            ;;
        --symlink)
            USE_SYMLINK=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--profile <name>] [--symlink]"
            echo ""
            echo "Options:"
            echo "  --profile <name>  Install to profile plugins dir instead of global"
            echo "  --symlink         Create symlink instead of copy (for development)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [[ -n "$PROFILE" ]]; then
    TARGET_DIR="$HOME/.hermes/profiles/$PROFILE/plugins/$PLUGIN_NAME"
else
    TARGET_DIR="$GLOBAL_DIR"
fi

echo "Installing $PLUGIN_NAME to: $TARGET_DIR"
echo "Mode: $(if $USE_SYMLINK; then echo 'symlink'; else echo 'copy'; fi)"

mkdir -p "$TARGET_DIR"

if $USE_SYMLINK; then
    # Remove existing files/dirs (but keep __pycache__)
    for f in __init__.py plugin.yaml; do
        rm -f "$TARGET_DIR/$f"
    done
    # Create symlinks
    ln -sf "$SCRIPT_DIR/__init__.py" "$TARGET_DIR/__init__.py"
    ln -sf "$SCRIPT_DIR/plugin.yaml" "$TARGET_DIR/plugin.yaml"
    echo "✅ Symlinked. Edit source in $SCRIPT_DIR — changes take effect on Hermes restart."
else
    cp "$SCRIPT_DIR/__init__.py" "$TARGET_DIR/__init__.py"
    cp "$SCRIPT_DIR/plugin.yaml" "$TARGET_DIR/plugin.yaml"
    echo "✅ Copied. Run again to update after changes."
fi

echo ""
echo "Next: restart Hermes to load the plugin."
