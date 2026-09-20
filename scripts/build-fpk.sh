#!/usr/bin/env bash
# 构建「直链」飞牛 .fpk 安装包
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/zhilian-fpk.XXXXXX")"
cleanup() { rm -rf "$TMP" >/dev/null 2>&1 || true; }
trap cleanup EXIT

VER="$(grep -m1 '^version=' "$ROOT/manifest" | cut -d= -f2)"
[ -n "$VER" ] || { echo "无法从 manifest 解析版本"; exit 1; }

FNPACK=""
if [ -x "$ROOT/.verify/fnpack" ]; then
  FNPACK="$ROOT/.verify/fnpack"
elif command -v fnpack >/dev/null 2>&1; then
  FNPACK="$(command -v fnpack)"
else
  OS="$(uname -s)"
  ARCH="$(uname -m)"
  case "$OS" in
    Linux)
      case "$ARCH" in
        aarch64|arm64) FNPACK_URL="https://static2.fnnas.com/fnpack/fnpack-1.2.3-linux-arm64" ;;
        *) FNPACK_URL="https://static2.fnnas.com/fnpack/fnpack-1.2.3-linux-amd64" ;;
      esac
      ;;
    Darwin)
      case "$ARCH" in
        arm64) FNPACK_URL="https://static2.fnnas.com/fnpack/fnpack-1.2.3-darwin-arm64" ;;
        *) FNPACK_URL="https://static2.fnnas.com/fnpack/fnpack-1.2.3-darwin-amd64" ;;
      esac
      ;;
    *) FNPACK_URL="https://static2.fnnas.com/fnpack/fnpack-1.2.3-windows-amd64" ;;
  esac
  FNPACK="$TMP/fnpack"
  echo "[build-fpk] 下载 fnpack: $FNPACK_URL"
  curl -fsSL -o "$FNPACK" "$FNPACK_URL"
  chmod +x "$FNPACK"
fi

mkdir -p "$OUT"
BUILD="$TMP/build"
rm -rf "$BUILD"
mkdir -p "$BUILD"

for item in manifest LICENSE ICON.PNG ICON_256.PNG cmd config app; do
  cp -R "$ROOT/$item" "$BUILD/"
done
mkdir -p "$BUILD/wizard"

chmod +x "$BUILD/cmd/"* "$BUILD/app/ui/index.cgi" 2>/dev/null || true

echo "[build-fpk] fnpack 校验并打包 ..."
( cd "$BUILD" && "$FNPACK" build --directory "$BUILD" )

SRC="$(ls "$BUILD"/*.fpk 2>/dev/null | head -1)"
[ -n "$SRC" ] || { echo "[build-fpk] 未找到 fnpack 产物"; exit 1; }

OUTNAME="zhilian-${VER}.fpk"
mv "$SRC" "$OUT/$OUTNAME"
echo "[build-fpk] 产物: $OUT/$OUTNAME ($(wc -c < "$OUT/$OUTNAME") bytes)"
