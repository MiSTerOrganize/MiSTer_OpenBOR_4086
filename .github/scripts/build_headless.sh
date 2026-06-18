#!/bin/bash
# build_headless.sh — Build OpenBOR Build 4086 (commit af23dc9c) HEADLESS on
# native x86-64 for the diff/debug harness. SDL 1.2 sister of the 7533 harness
# (7533 is SDL2). NOT the MiSTer ARM ship build (build_mister_arm.sh).
# MILESTONE 1a: prove it compiles on x86 with distro SDL 1.2 + stock target.
set +e
set -x

REPO="$(pwd)"

APTOPT="-o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30"
sudo apt-get $APTOPT update -qq
# 4086 = SDL 1.2.15 + SDL_gfx 2.0.26 (distro: libsdl1.2-dev + libsdl-gfx1.2-dev)
sudo apt-get $APTOPT install -y -qq build-essential gcc make pkg-config git python3 \
  libsdl1.2-dev libsdl-gfx1.2-dev libpng-dev zlib1g-dev libvorbis-dev libogg-dev \
  libvpx-dev
which gcc sdl-config || { echo "ERROR: toolchain/SDL1.2 install failed"; exit 1; }
echo "SDL1.2 cflags: $(sdl-config --cflags 2>&1)"; echo "SDL1.2 libs: $(sdl-config --libs 2>&1)"

cd /tmp
rm -rf openbor
git clone --filter=blob:none https://github.com/DCurrent/openbor.git
cd openbor
git checkout af23dc9c
cd engine 2>/dev/null || cd .   # 4086 layout: source may be at root or engine/

cat > version.h << 'VERSIONEOF'
#ifndef VERSION_H
#define VERSION_H
#define VERSION_NAME "OpenBOR"
#define VERSION_MAJOR "3"
#define VERSION_MINOR "0"
#define VERSION_BUILD "4086"
#define VERSION "v"VERSION_MAJOR"."VERSION_MINOR" Build "VERSION_BUILD
#endif
VERSIONEOF

sed -i 's/stricmp/strcasecmp/g' openbor.h 2>/dev/null
sed -i 's/-Werror/-Wno-error/g' Makefile 2>/dev/null

echo "=== available BUILD_ targets in Makefile ==="
grep -nE "^ifdef BUILD_" Makefile | head

echo "=== make BUILD_LINUX_LE_x86_64=1 (milestone 1a) ==="
make BUILD_LINUX_LE_x86_64=1 -j$(nproc)
RC=$?
echo "make rc=$RC"
ls -lh OpenBOR.elf OpenBOR 2>/dev/null
if [ -f OpenBOR.elf ] || [ -f OpenBOR ]; then
  echo "HEADLESS BUILD OK (4086 milestone 1a)"
  cp -f OpenBOR.elf /tmp/OpenBOR_headless 2>/dev/null || cp -f OpenBOR /tmp/OpenBOR_headless 2>/dev/null
else
  echo "HEADLESS BUILD FAILED — see make output above"
  exit 1
fi
