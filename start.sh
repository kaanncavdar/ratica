#!/usr/bin/env sh
# Ratica launcher for Linux and macOS.
# First run installs uv (a small Python manager) and Ratica's packages; later runs start at once.
set -e
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv, a small tool that manages Python for Ratica..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "Starting Ratica. The first start takes a few minutes while packages are installed..."
exec uv run --frozen --no-dev ratica-gui
