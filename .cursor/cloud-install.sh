#!/usr/bin/env bash
# Idempotent dependency install for the Ai Coach MyKo multi-repo workspace.
# Runs from whatever checkout root the Cloud Agent build uses. Resolves sibling
# repositories relative to this file, then falls back to known workspace roots.
set -euo pipefail

log() { printf '[cloud-install] %s\n' "$*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRIMARY="$(cd "$SCRIPT_DIR/.." && pwd)"
PARENT="$(cd "$PRIMARY/.." && pwd)"

log "primary=$PRIMARY"
log "parent=$PARENT"
log "parent listing: $(ls -1 "$PARENT" | tr '\n' ' ')"

find_repo() {
  local name="$1"
  local candidate
  local roots=(
    "$PARENT"
    "/workspace"
    "/workspace/repos"
    "/agent"
    "/agent/repos"
  )
  for root in "${roots[@]}"; do
    candidate="$root/$name"
    if [[ -d "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

log "upgrading pip"
python3 -m pip install --upgrade pip --break-system-packages
log "installing Ai Coach Python dependencies (requirements.txt)"
python3 -m pip install --break-system-packages -r "$PRIMARY/requirements.txt"

# npm 10's arborist crashes with "edgesOut" on the peer graphs in this workspace.
ensure_npm() {
  local major
  major="$(npm --version | cut -d. -f1)"
  if [[ "$major" -ge 11 ]]; then
    log "npm $(npm --version)"
    return 0
  fi
  local node_bin prefix
  node_bin="$(readlink -f "$(command -v node)")"
  prefix="$(dirname "$(dirname "$node_bin")")"
  log "upgrading npm $(npm --version) to 11.21.1 in $prefix"
  if [[ -w "$prefix" ]]; then
    npm install -g npm@11.21.1 --prefix "$prefix"
  else
    sudo npm install -g npm@11.21.1 --prefix "$prefix"
  fi
  hash -r
  log "npm $(npm --version)"
}

install_npm() {
  local dir="$1"
  if [[ ! -f "$dir/package.json" ]]; then
    log "no package.json in $dir"
    return 0
  fi
  log "node dependencies in $dir"
  # Browser binaries are large and not required for the unit-test scripts.
  # Agents that need Playwright can run: npx playwright install
  export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
  if [[ -f "$dir/bun.lock" && ! -f "$dir/package-lock.json" ]] && command -v bun >/dev/null 2>&1; then
    (cd "$dir" && bun install --frozen-lockfile)
    return 0
  fi
  if [[ -f "$dir/package-lock.json" ]]; then
    if (cd "$dir" && npm ci --no-audit --no-fund); then
      return 0
    fi
    # Some lockfiles are missing transitive entries. Install from package.json
    # and put the committed lockfile back so git stays clean.
    log "package-lock.json is out of sync in $dir; installing from package.json"
    (
      cd "$dir"
      rm -rf node_modules
      mv package-lock.json package-lock.json.cloud-bak
      restore_lock() {
        if [[ -f package-lock.json.cloud-bak ]]; then
          rm -f package-lock.json
          mv package-lock.json.cloud-bak package-lock.json
        fi
      }
      trap restore_lock EXIT
      set +e
      npm install --no-audit --no-fund --no-package-lock --legacy-peer-deps
      status=$?
      set -e
      restore_lock
      trap - EXIT
      exit "$status"
    )
    return 0
  fi
  (cd "$dir" && npm install --no-audit --no-fund --no-package-lock --legacy-peer-deps)
}

ensure_bun() {
  if command -v bun >/dev/null 2>&1; then
    log "bun $(bun --version)"
    return 0
  fi
  log "installing bun"
  curl -fsSL https://bun.sh/install | bash
  sudo ln -sf "$HOME/.bun/bin/bun" /usr/local/bin/bun
  hash -r
  log "bun $(bun --version)"
}

ensure_npm

NODE_REPOS=(
  aurora
  blend-maple-dawn-valley
  cabin-harbor-prism-brook
  Kai_Kings_Google_AI_Studio
)

for name in "${NODE_REPOS[@]}"; do
  if dir="$(find_repo "$name")"; then
    install_npm "$dir"
  else
    log "ERROR: repository $name was not checked out"
    exit 1
  fi
done

ensure_bun
if dir="$(find_repo lumix-studio-media-suite)"; then
  install_npm "$dir"
else
  log "ERROR: repository lumix-studio-media-suite was not checked out"
  exit 1
fi

if dir="$(find_repo Shooting-Game)"; then
  if [[ -f "$dir/requirements.txt" ]]; then
    log "installing Shooting-Game Python dependencies"
    python3 -m pip install --break-system-packages -r "$dir/requirements.txt"
  fi
else
  log "ERROR: repository Shooting-Game was not checked out"
  exit 1
fi

# User-site scripts (pytest, pip) are not on the default PATH. Login shells
# read /etc/profile.d, and a pytest symlink covers non-login commands.
sudo tee /etc/profile.d/cursor-user-local.sh >/dev/null <<'EOF'
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) export PATH="$HOME/.local/bin:$PATH" ;;
esac
EOF
if [[ -x "$HOME/.local/bin/pytest" ]]; then
  sudo ln -sfn "$HOME/.local/bin/pytest" /usr/local/bin/pytest
fi

log "done"
