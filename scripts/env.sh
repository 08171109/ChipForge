CHIPFORGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export CHIPFORGE_ROOT
export PATH="$CHIPFORGE_ROOT/tools/node/bin:$CHIPFORGE_ROOT/.venv/bin:$PATH"
export AGH_HOME="${CHIPFORGE_AGH_HOME:-$CHIPFORGE_ROOT/runtime/agh-home}"
export AGNES_PROFILE=local-dev
export PDK_ROOT="${PDK_ROOT:-$CHIPFORGE_ROOT/pdk}"
export PDK=sky130A
export LIBRELANE_IMAGE_OVERRIDE=ghcr.io/librelane/librelane:3.0.14
export COREPACK_HOME="$CHIPFORGE_ROOT/tools/corepack"
