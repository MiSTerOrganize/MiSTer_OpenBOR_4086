#!/usr/bin/env python3
"""
apply_patches.py — Apply all MiSTer patches to OpenBOR 3979 source tree.

Usage: python3 apply_patches.py <openbor_source_dir> <patches_dir>

Applies:
  1. Makefile: adds BUILD_MISTER target
  2. openbor.c: replaces pausemenu() with custom 4-item menu
  3. sdl/video.c: intercepts SDL_Flip with NativeVideoWriter
  4. sdl/control.c: replaces control_update() with DDR3 joystick reading
  5. sdl/sdlport.c: replaces main() with NativeVideoWriter init + OSD PAK loading
  6. source/utils.c: redirects save path to /media/fat/saves/OpenBOR/
"""

import sys
import os

def read(path):
    with open(path, 'r') as f:
        return f.read()

def write(path, content):
    with open(path, 'w') as f:
        f.write(content)

def extract_function(source, func_sig):
    """Extract a C function body starting from its signature."""
    start = source.find(func_sig)
    if start < 0:
        return None, -1, -1
    brace = 0
    found_open = False
    end = start
    for i in range(start, len(source)):
        if source[i] == '{':
            brace += 1
            found_open = True
        elif source[i] == '}':
            brace -= 1
        if found_open and brace == 0:
            end = i + 1
            break
    return source[start:end], start, end

def replace_function(source, func_sig, replacement_file, patches_dir):
    """Replace a function in source with the function from a patch file."""
    patch = read(os.path.join(patches_dir, replacement_file))
    # Find the function in the patch file
    func_start = patch.find(func_sig)
    if func_start < 0:
        print(f"  ERROR: Could not find '{func_sig}' in {replacement_file}")
        return source
    replacement = patch[func_start:]
    # Find and replace in source
    _, start, end = extract_function(source, func_sig)
    if start < 0:
        print(f"  ERROR: Could not find '{func_sig}' in source")
        return source
    return source[:start] + replacement + source[end:]

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <openbor_dir> <patches_dir>")
        sys.exit(1)

    obor = sys.argv[1]
    patches = sys.argv[2]

    # ── 1. Patch Makefile ─────────────────────────────────────────────
    print("Patching Makefile...")
    mf = read(os.path.join(obor, 'Makefile'))

    # Add BUILD_MISTER target block after BUILD_OPENDINGUX endif
    mister_target = """
ifdef BUILD_MISTER
TARGET          = $(VERSION_NAME).elf
TARGET_FINAL    = $(VERSION_NAME)
TARGET_PLATFORM = LINUX
BUILD_SDL       = 1
BUILD_GFX       = 1
BUILD_PTHREAD   = 1
BUILD_SDL_IO    = 1
BUILD_VORBIS    = 1
BUILDING        = 1
CC              = gcc
OBJTYPE         = elf
ARCHFLAGS       = -mcpu=cortex-a9 -mfloat-abi=hard -mfpu=neon
INCLUDES        = $(SDL_PREFIX)/include \\
                  $(SDL_PREFIX)/include/SDL
LIBRARIES       = $(SDL_PREFIX)/lib
ifeq ($(BUILD_MISTER), 0)
BUILD_DEBUG     = 1
endif
endif

"""
    # Insert after the BUILD_OPENDINGUX endif
    marker = "ifeq ($(BUILD_OPENDINGUX), 0)\nBUILD_DEBUG     = 1\nendif\nendif"
    mf = mf.replace(marker, marker + "\n" + mister_target)

    # Add MISTER_NATIVE_VIDEO CFLAG
    mf = mf.replace(
        "ifdef BUILD_SDL\nCFLAGS \t       += -DSDL\nendif",
        "ifdef BUILD_SDL\nCFLAGS \t       += -DSDL\nendif\n\n\nifdef BUILD_MISTER\nCFLAGS         += -DMISTER_NATIVE_VIDEO -fcommon -Wno-error\nendif"
    )

    # Add native_video_writer.o and native_audio_writer.o to objects
    mf = mf.replace(
        "sdl/menu.o                                                                        \nendif",
        "sdl/menu.o                                                                        \nendif\n\n\nifdef BUILD_MISTER\nGAME_CONSOLE   += native_video_writer.o native_audio_writer.o\nendif"
    )

    # Add strip rule
    mf = mf.replace(
        "ifdef BUILD_OPENDINGUX\nSTRIP           = $(OPENDINGUX_TOOLCHAIN_PREFIX)/bin/mipsel-linux-strip $(TARGET) -o $(TARGET_FINAL)\nendif",
        "ifdef BUILD_OPENDINGUX\nSTRIP           = $(OPENDINGUX_TOOLCHAIN_PREFIX)/bin/mipsel-linux-strip $(TARGET) -o $(TARGET_FINAL)\nendif\nifdef BUILD_MISTER\nSTRIP           = strip $(TARGET) -o $(TARGET_FINAL)\nendif"
    )

    # Add -ldl for MiSTer (needed for dlopen/dlsym/dlclose in static SDL)
    mf = mf.replace(
        "LIBS           += -lpng -lz -lm",
        "LIBS           += -lpng -lz -lm\n\n\nifdef BUILD_MISTER\nLIBS           += -ldl\nendif"
    )

    write(os.path.join(obor, 'Makefile'), mf)
    print("  Makefile patched.")

    # ── 2. Patch openbor.c — replace pausemenu() ─────────────────────
    print("Patching openbor.c (pausemenu)...")
    src = read(os.path.join(obor, 'openbor.c'))
    src = replace_function(src, "void pausemenu()", "pausemenu_patch.c", patches)
    write(os.path.join(obor, 'openbor.c'), src)
    print("  pausemenu() replaced.")

    # ── 3. sdl/video.c -- NO LONGER PATCHED ────────────────────────
    # We previously intercepted video_copy_screen() to grab OpenBOR's
    # vscreen and convert it ourselves. That tripped over OpenBOR's
    # PIXEL_32 blend bugs (R/B swap in some inline blends) which only
    # bit certain enemy sprites. Now we let video_copy_screen run
    # untouched -- OpenBOR's normal SDL pipeline (vscreen -> bscreen
    # -> SDL_BlitSurface -> screen surface) handles all format
    # conversion via SDL's well-tested code. Our patched dummy video
    # driver (see patch_sdl_dummy.py) reads screen->pixels in its
    # UpdateRects hook and writes RGB565 to DDR3.
    print("Skipping sdl/video.c -- using SDL dummy-driver DDR3 bridge instead.")

    # ── 4. Patch sdl/control.c — replace control_update() ────────────
    print("Patching sdl/control.c (input mapping)...")
    src = read(os.path.join(obor, 'sdl/control.c'))

    # Add include
    src = src.replace(
        '#include "openbor.h"',
        '#include "openbor.h"\n#ifdef MISTER_NATIVE_VIDEO\n#include "native_video_writer.h"\n#endif'
    )

    src = replace_function(src, "void control_update(s_playercontrols ** playercontrols, int numplayers)", "control_patch.c", patches)
    write(os.path.join(obor, 'sdl/control.c'), src)
    print("  control_update() replaced.")

    # ── 5. Patch sdl/sdlport.c — replace main() ─────────────────────
    print("Patching sdl/sdlport.c (main + NativeVideoWriter init)...")
    src = read(os.path.join(obor, 'sdl/sdlport.c'))

    # Add includes
    src = src.replace(
        '#include "menu.h"',
        '#include "menu.h"\n#ifdef MISTER_NATIVE_VIDEO\n#include "native_video_writer.h"\n#include "native_audio_writer.h"\n#include <sys/stat.h>\n#include <stdlib.h>\n#endif'
    )

    # Replace main() — it's the last function in the file
    main_sig = "int main(int argc, char *argv[])"
    start = src.find(main_sig)
    if start >= 0:
        patch = read(os.path.join(patches, 'sdlport_patch.c'))
        func_start = patch.find(main_sig)
        replacement = patch[func_start:]
        src = src[:start] + replacement + "\n"

    write(os.path.join(obor, 'sdl/sdlport.c'), src)
    print("  main() replaced.")

    # ── 6. Patch source/utils.c — redirect save path ─────────────────
    print("Patching source/utils.c (save path redirect)...")
    src = read(os.path.join(obor, 'source/utils.c'))

    old_macro = '#define COPY_ROOT_PATH(buf, name) strncpy(buf, "./", 2); strncat(buf, name, strlen(name)); strncat(buf, "/", 1);'

    new_macro = """#ifdef MISTER_NATIVE_VIDEO
#define COPY_ROOT_PATH(buf, name) \\
    do { \\
        if (strcmp(name, "Saves") == 0) { \\
            strcpy(buf, "/media/fat/saves/OpenBOR/"); \\
        } else { \\
            strncpy(buf, "./", 2); strncat(buf, name, strlen(name)); strncat(buf, "/", 1); \\
        } \\
    } while(0)
#else
#define COPY_ROOT_PATH(buf, name) strncpy(buf, "./", 2); strncat(buf, name, strlen(name)); strncat(buf, "/", 1);
#endif"""

    src = src.replace(old_macro, new_macro)
    write(os.path.join(obor, 'source/utils.c'), src)
    print("  Save path redirected.")

    # -- 7. Replace sdl/sblaster.c with MiSTer DDR3 audio backend --------
    print("Patching sdl/sblaster.c (DDR3 audio backend)...")
    sb = read(os.path.join(patches, 'sblaster_patch.c'))
    write(os.path.join(obor, 'sdl/sblaster.c'), sb)
    print("  sdl/sblaster.c replaced.")

    # -- 8. Fix R/B swap bug in 32-bit blend functions ------------------
    # pixelformat.c's blend_screen32 / blend_multiply32 / blend_half32
    # pass arguments to _color() in swapped (B, G, R) order when they
    # use their inline math path. That path only runs when blendtables
    # is NULL, which is ALWAYS the case in PIXEL_32 mode (set_blendtables
    # is gated on screenformat == PIXEL_8 in openbor.c). Result: every
    # sprite drawn with a screen / multiply / half blend comes out with
    # its R and B channels swapped. Player draws are direct copies and
    # don't hit this; enemies using hit-flash / shadow / alpha blend do.
    #
    # Fix: swap the first and third args of the inline _color(...) calls
    # so argument order matches the _color(r, g, b) signature.
    print("Patching source/gamelib/pixelformat.c (32-bit blend R/B fix)...")
    pf_path = os.path.join(obor, 'source/gamelib/pixelformat.c')
    pf = read(pf_path)
    fixes = [
        (
            "return _color(_screen(color1 >> 16, color2 >> 16),\n"
            "                  _screen((color1 & 0xFF00) >> 8, (color2 & 0xFF00) >> 8),\n"
            "                  _screen(color1 & 0xFF, color2 & 0xFF));",
            "return _color(_screen(color1 & 0xFF, color2 & 0xFF),\n"
            "                  _screen((color1 & 0xFF00) >> 8, (color2 & 0xFF00) >> 8),\n"
            "                  _screen(color1 >> 16, color2 >> 16));"
        ),
        (
            "return _color(_multiply(color1 >> 16, color2 >> 16),\n"
            "                  _multiply((color1 & 0xFF00) >> 8, (color2 & 0xFF00) >> 8),\n"
            "                  _multiply(color1 & 0xFF, color2 & 0xFF));",
            "return _color(_multiply(color1 & 0xFF, color2 & 0xFF),\n"
            "                  _multiply((color1 & 0xFF00) >> 8, (color2 & 0xFF00) >> 8),\n"
            "                  _multiply(color1 >> 16, color2 >> 16));"
        ),
        (
            "return _color(((color1 >> 16) + (color2 >> 16)) >> 1,\n"
            "                  (((color1 & 0xFF00) >> 8) + ((color2 & 0xFF00) >> 8)) >> 1,\n"
            "                  ((color1 & 0xFF) + (color2 & 0xFF)) >> 1);",
            "return _color(((color1 & 0xFF) + (color2 & 0xFF)) >> 1,\n"
            "                  (((color1 & 0xFF00) >> 8) + ((color2 & 0xFF00) >> 8)) >> 1,\n"
            "                  ((color1 >> 16) + (color2 >> 16)) >> 1);"
        ),
    ]
    applied = 0
    for old, new in fixes:
        if old in pf:
            pf = pf.replace(old, new)
            applied += 1
        else:
            print(f"  WARN: blend fix pattern not found (already patched?):\n    {old[:60]}...")

    # -- Default pixelformat/screenformat to PIXEL_32 -------------------
    # Many PAKs (e.g. "A Tale of Vengeance") ship without data/video.txt.
    # OpenBOR's built-in defaults are PIXEL_8 for both globals, which
    # means every character on screen has to share one 256-colour
    # palette -- that's why enemies look miscoloured in such mods.
    # Mods that combine characters from different games (SF/KOF/FF)
    # expect PIXEL_32 so each character gets its own palette. Flip the
    # defaults here; a PAK with an explicit colourdepth command still
    # gets its wish because video.txt parsing runs later and overrides.
    old_defaults = ("int pixelformat = PIXEL_8;\n"
                    "int screenformat = PIXEL_8;")
    new_defaults = ("int pixelformat = PIXEL_32;\n"
                    "int screenformat = PIXEL_32;")
    if old_defaults in pf:
        pf = pf.replace(old_defaults, new_defaults)
        print("  Default pixelformat/screenformat: PIXEL_8 -> PIXEL_32")
    else:
        print("  WARN: pixelformat default pattern not found")

    write(pf_path, pf)
    print(f"  {applied}/{len(fixes)} blend R/B fixes applied.")

    print("\nAll patches applied successfully.")

if __name__ == '__main__':
    main()
