#!/usr/bin/env bash
# mangakit installer: downloads resvg 0.49.0 and the four OFL fonts from their upstream releases,
# checks every sha256, installs the Python package (editable), and copies the seven skills.
#
#   ./install.sh [--skills-dir DIR] [--no-skills] [--no-pip] [--python PY]
#
# --skills-dir defaults to ~/.claude/skills (Claude Code / Cursor-style agents read SKILL.md folders
# from there). For an agent with its own skill library (e.g. Grok Bot), point --skills-dir at that
# library's folder, or upload each skills/<name>/SKILL.md through the agent's own skill tools.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="${HOME}/.claude/skills"
DO_SKILLS=1
DO_PIP=1
PY="${PYTHON:-python3}"
while [ $# -gt 0 ]; do
  case "$1" in
    --skills-dir) SKILLS_DIR="$2"; shift 2 ;;
    --no-skills) DO_SKILLS=0; shift ;;
    --no-pip) DO_PIP=0; shift ;;
    --python) PY="$2"; shift 2 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

need() { command -v "$1" >/dev/null 2>&1 || { echo "install.sh: needs '$1'" >&2; exit 1; }; }
need curl
if command -v sha256sum >/dev/null 2>&1; then SHA() { sha256sum "$1" | cut -d' ' -f1; }
else need shasum; SHA() { shasum -a 256 "$1" | cut -d' ' -f1; }; fi

fetch() {  # url dest sha256
  local url="$1" dest="$2" want="$3" tmp
  if [ -f "$dest" ] && [ "$(SHA "$dest")" = "$want" ]; then echo "  ok      $(basename "$dest")"; return; fi
  tmp="$(mktemp)"
  curl -fsSL --retry 3 -o "$tmp" "$url" || { echo "install.sh: download failed: $url" >&2; rm -f "$tmp"; exit 1; }
  local got; got="$(SHA "$tmp")"
  if [ "$got" != "$want" ]; then
    echo "install.sh: sha256 mismatch for $url" >&2; echo "  want $want" >&2; echo "  got  $got" >&2
    rm -f "$tmp"; exit 1
  fi
  mkdir -p "$(dirname "$dest")"; mv "$tmp" "$dest"; echo "  fetched $(basename "$dest")"
}

# ---- resvg 0.49.0 (github.com/linebender/resvg releases) -------------------------------------
RESVG_VER=0.49.0
RESVG_BASE="https://github.com/linebender/resvg/releases/download/v${RESVG_VER}"
OS="$(uname -s)"; ARCH="$(uname -m)"
case "$OS/$ARCH" in
  Linux/x86_64)  ASSET=resvg-linux-x86_64.tar.gz;  ASSET_SHA=216637e75e909e53e3098b0875cd5f7da2fdc8b4359771b4a29b539afff9d3f5
                 BIN_SHA=1fc436320a57d0a47709fc43de7b377687e0836c556708e83b79eb1a018d2304 ;;
  Darwin/arm64)  ASSET=resvg-macos-aarch64.zip;    ASSET_SHA=847acb5210c7c6244b5e8f07dd62fa1ce596108cce8193628ebfd5750504b259
                 BIN_SHA=c3826d364251050cee2f6e348a7cfd65b828ddfb90aa447b6858e4fe1fbfd530 ;;
  *) echo "install.sh: no pinned resvg build for $OS/$ARCH (supported: Linux x86_64, macOS arm64)." >&2
     echo "  Put a resvg ${RESVG_VER} binary at vendor/resvg-${RESVG_VER}/resvg or on PATH and rerun with the same flags." >&2
     ASSET="" ;;
esac
RESVG="$HERE/vendor/resvg-${RESVG_VER}/resvg"
echo "resvg ${RESVG_VER}"
if [ -n "${ASSET}" ]; then
  if [ -x "$RESVG" ] && [ "$(SHA "$RESVG")" = "$BIN_SHA" ]; then echo "  ok      resvg"
  else
    DL="$(mktemp -d)"
    fetch "$RESVG_BASE/$ASSET" "$DL/$ASSET" "$ASSET_SHA"
    case "$ASSET" in
      *.tar.gz) tar -xzf "$DL/$ASSET" -C "$DL" ;;
      *.zip) need unzip; unzip -q -o "$DL/$ASSET" -d "$DL" ;;
    esac
    [ "$(SHA "$DL/resvg")" = "$BIN_SHA" ] || { echo "install.sh: resvg binary sha256 mismatch" >&2; exit 1; }
    mkdir -p "$(dirname "$RESVG")"; mv "$DL/resvg" "$RESVG"; chmod +x "$RESVG"; rm -rf "$DL"
    [ "$OS" = Darwin ] && xattr -d com.apple.quarantine "$RESVG" 2>/dev/null || true
    echo "  fetched resvg -> vendor/resvg-${RESVG_VER}/resvg"
  fi
elif ! command -v resvg >/dev/null 2>&1 && [ ! -x "$RESVG" ]; then
  exit 1
fi

# ---- fonts (SIL OFL 1.1) from github.com/google/fonts, pinned to one commit ------------------
GF="https://raw.githubusercontent.com/google/fonts/cc5661d43cd4f9aad5567033a8e15ca28dc35c86/ofl"
FONTS="$HERE/mangakit/fonts"
echo "fonts"
fetch "$GF/comicneue/ComicNeue-Bold.ttf"       "$FONTS/ComicNeue-Bold.ttf"       3e7e5fccfd7e0788f317b43312151c1bd5cf058c9697a8d83eac3939050bd61e
fetch "$GF/comicneue/ComicNeue-BoldItalic.ttf" "$FONTS/ComicNeue-BoldItalic.ttf" 5c312c2a2fa64eee82f3b87fcfab8f3b12a5e59b043124401d322eb323cfbf16
fetch "$GF/comicneue/ComicNeue-Regular.ttf"    "$FONTS/ComicNeue-Regular.ttf"    a0ee5a37c8b27c4db0700137d928598b1e23b0089e1546a8961909176b779360
fetch "$GF/bangers/Bangers-Regular.ttf"        "$FONTS/Bangers-Regular.ttf"      4160a7311de9342674cce9160cde9fcbb30f48190397d86ff1b70b455af65824
# the example project pins the same fonts
mkdir -p "$HERE/example/fonts"
cp "$FONTS"/*.ttf "$FONTS"/OFL-*.txt "$HERE/example/fonts/"

# ---- python package -----------------------------------------------------------------------
if [ "$DO_PIP" = 1 ]; then
  echo "pip install -e ."
  "$PY" -m pip install -q -e "$HERE" ${PIP_FLAGS:-}
fi

# ---- skills -----------------------------------------------------------------------------
if [ "$DO_SKILLS" = 1 ]; then
  echo "skills -> $SKILLS_DIR"
  mkdir -p "$SKILLS_DIR"
  for d in "$HERE"/skills/*/; do
    n="$(basename "$d")"; mkdir -p "$SKILLS_DIR/$n"; cp "$d/SKILL.md" "$SKILLS_DIR/$n/SKILL.md"; echo "  $n"
  done
fi

echo "done. Try: mangakit docs; cd example && mangakit story check && mangakit render p002"
