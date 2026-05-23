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
  6. source/utils.c: redirects save path to /media/fat/saves/OpenBOR_4086/
"""

import sys
import os

def read(path):
    # Explicit UTF-8 encoding — Windows defaults to cp1252 which mangles
    # any non-ASCII byte in patch content (mid-dash, em-dash, arrow, etc.).
    # Linux CI defaults to UTF-8 already; this just makes Windows
    # dry-runs match CI behavior.
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        return f.read()

def write(path, content):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)

def strict_replace(content, old, new, label):
    """Replace `old` with `new` in content; RAISE if `old` not found.

    Use this instead of `content.replace(old, new)` for patches where a
    silent no-op would corrupt the build. Mirrored from 7533 2026-05-22
    (was originally added there 2026-05-19 after the ATOV palette session
    surfaced multiple silent `.replace()` no-ops that masked the fix for
    two deploys + a wasted hardware test cycle). 4086 reached full
    strict_replace coverage 2026-05-22 — all 15 unconditional `.replace()`
    calls migrated. 3 conditional `.replace()` sites remain (menu_anchor
    loop, logsDir if-guarded, pixelformat blend R/B fixes list) — those
    handle pattern variability between r3979 and r4086 upstream variants;
    they're intentionally conditional and use `if pattern in source`
    guards before the replace, so they CAN'T silently no-op the way
    bare `.replace()` calls outside guards would.
    """
    if old not in content:
        raise RuntimeError(
            f"strict_replace failed for '{label}': pattern not found.\n"
            f"  First 80 chars of expected: {old[:80]!r}\n"
            f"  Verify the pattern matches PRISTINE upstream at "
            f"https://raw.githubusercontent.com/DCurrent/openbor/af23dc9c/engine/..."
        )
    return content.replace(old, new)

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
    mf = strict_replace(mf, marker, marker + "\n" + mister_target,
                        'Makefile BUILD_OPENDINGUX marker for BUILD_MISTER target')

    # Add MISTER_NATIVE_VIDEO CFLAG + suppress warnings that v4153's
    # older C style triggers under modern GCC (stringop-overflow,
    # multistatement-macros, etc.)
    mf = strict_replace(
        mf,
        "ifdef BUILD_SDL\nCFLAGS \t       += -DSDL\nendif",
        "ifdef BUILD_SDL\nCFLAGS \t       += -DSDL\nendif\n\n\nifdef BUILD_MISTER\nCFLAGS         += -DMISTER_NATIVE_VIDEO -fcommon -Wno-error -O1 -g -rdynamic -funwind-tables -fasynchronous-unwind-tables -mapcs-frame\nendif",
        'Makefile BUILD_SDL CFLAGS append BUILD_MISTER block'
    )

    # Add native_video_writer.o and native_audio_writer.o to objects.
    # r3979 has trailing spaces after menu.o; r4086 doesn't. Match both.
    menu_anchor = None
    for pattern in ["sdl/menu.o                                                                        \nendif",
                     "sdl/menu.o\nendif"]:
        if pattern in mf:
            menu_anchor = pattern
            break
    if menu_anchor:
        mf = mf.replace(
            menu_anchor,
            menu_anchor + "\n\n\nifdef BUILD_MISTER\nGAME_CONSOLE   += native_video_writer.o native_audio_writer.o\nendif",
            1
        )
    else:
        print("  WARN: sdl/menu.o endif pattern not found for object injection")

    # Add strip rule
    mf = strict_replace(
        mf,
        "ifdef BUILD_OPENDINGUX\nSTRIP           = $(OPENDINGUX_TOOLCHAIN_PREFIX)/bin/mipsel-linux-strip $(TARGET) -o $(TARGET_FINAL)\nendif",
        "ifdef BUILD_OPENDINGUX\nSTRIP           = $(OPENDINGUX_TOOLCHAIN_PREFIX)/bin/mipsel-linux-strip $(TARGET) -o $(TARGET_FINAL)\nendif\nifdef BUILD_MISTER\nSTRIP           = strip $(TARGET) -o $(TARGET_FINAL)\nendif",
        'Makefile BUILD_OPENDINGUX strip rule + BUILD_MISTER strip rule'
    )

    # Add -ldl for MiSTer (needed for dlopen/dlsym/dlclose in static SDL)
    mf = strict_replace(
        mf,
        "LIBS           += -lpng -lz -lm",
        "LIBS           += -lpng -lz -lm\n\n\nifdef BUILD_MISTER\nLIBS           += -ldl\nendif",
        'Makefile LIBS add -ldl for BUILD_MISTER'
    )

    write(os.path.join(obor, 'Makefile'), mf)
    print("  Makefile patched.")

    # ── 2. Patch openbor.c — replace pausemenu() ─────────────────────
    print("Patching openbor.c (pausemenu)...")
    src = read(os.path.join(obor, 'openbor.c'))
    src = replace_function(src, "void pausemenu()", "pausemenu_patch.c", patches)
    write(os.path.join(obor, 'openbor.c'), src)
    print("  pausemenu() replaced.")

    # ── 3. sdl/video.c -- stub SDL 2 API for SDL 1.2 build ─────────
    # r4086+ added unguarded SDL 2 calls (SDL_AllocPalette,
    # SDL_GetDesktopDisplayMode, etc.) in video init. Since we use
    # SDL_VIDEODRIVER=dummy and our DDR3 bridge, video.c's init just
    # needs to compile -- it doesn't have to produce real output.
    # Guard the SDL 2 calls so they're skipped on SDL 1.2.
    print("Patching sdl/video.c (SDL 1.2 compat stubs)...")
    vid_path = os.path.join(obor, 'sdl/video.c')
    vid = read(vid_path)
    # Add compat header after includes
    compat_block = """
/* MiSTer SDL 1.2 compat -- stub SDL 2 functions that r4086+ uses
   outside of #ifdef SDL2 guards. Our DDR3 bridge handles all real
   video output; these stubs just prevent link/compile errors. */
#ifndef SDL2
#include <stdlib.h>
typedef struct { int ncolors; SDL_Color *colors; } MiSTer_Palette;
static inline MiSTer_Palette *SDL_AllocPalette(int n) {
    MiSTer_Palette *p = (MiSTer_Palette*)malloc(sizeof(MiSTer_Palette));
    if(p) { p->ncolors = n; p->colors = (SDL_Color*)calloc(n, sizeof(SDL_Color)); }
    return p;
}
static inline void SDL_FreePalette(MiSTer_Palette *p) { if(p) { free(p->colors); free(p); } }
static inline int SDL_SetPaletteColors(MiSTer_Palette *p, const SDL_Color *c, int f, int n) {
    if(p && c) { int i; for(i=0;i<n&&(f+i)<p->ncolors;i++) p->colors[f+i]=c[i]; } return 0;
}
static inline int SDL_SetSurfacePalette(SDL_Surface *s, MiSTer_Palette *p) { (void)s;(void)p; return 0; }
typedef struct { int w, h, refresh_rate; unsigned format; } SDL_DisplayMode;
static inline int SDL_GetDesktopDisplayMode(int d, SDL_DisplayMode *m) {
    if(m){m->w=320;m->h=240;m->refresh_rate=60;m->format=0;} return 0;
}
#define SDL_Palette MiSTer_Palette
#endif
"""
    # Insert after the last #include line
    last_include = vid.rfind('#include')
    eol = vid.index('\n', last_include) + 1
    vid = vid[:eol] + compat_block + vid[eol:]

    # ── 3b. sdl/video.c — bypass SDL 1.2 surface chain in video_copy_screen ─
    # Architectural parity with 7533 (commit f1773f7, 2026-05-22). Stock
    # 4086 video_copy_screen does: memcpy(src->data -> screen->pixels) +
    # (bscreen path if 2x video mode) + SDL_Flip(screen). SDL_Flip in our
    # SDL 1.2 dummy driver triggers DUMMY_UpdateRects -> mister_present ->
    # DDR3 — that's TWO passes over the pixel data (memcpy then read+convert).
    # Direct write skips the wasted memcpy and gives ONE pass: src->data
    # -> NativeVideoWriter_WriteFrame -> DDR3 with anisotropic NN squish.
    #
    # Per the engine-function-replacement meta-rule
    # (feedback_engine_function_replacement_audit_side_effects.md): audited
    # pristine af23dc9c sdl/video.c::video_copy_screen for side-effects via
    # `grep -nE "sound_|music_|audio_|input_|render_|save_|net_|joy_|kbd_"
    # inside the function body` — ZERO matches. Only SDL_Lock/Unlock,
    # SDL_BlitSurface, SDL_Flip, SDL_framerateDelay. The framerate cap
    # (SDL_framerateDelay) is the one side-effect we MUST preserve in the
    # direct-write path. Other SDL calls are bypassed safely.
    #
    # Include native_video_writer.h via a separate guarded block.
    vid = strict_replace(
        vid,
        '#include "openbor.h"\n'
        '#include "gfxtypes.h"',
        '#include "openbor.h"\n'
        '#include "gfxtypes.h"\n'
        '#ifdef MISTER_NATIVE_VIDEO\n'
        '#include "native_video_writer.h"\n'
        '/* bytes_per_pixel is a file-scope static int defined later in\n'
        ' * this same file (line ~85 upstream af23dc9c). No extern needed. */\n'
        '#endif',
        'sdl/video.c include native_video_writer.h'
    )

    # Inject direct-write early-return inside video_copy_screen, right
    # after the width/height clamp and BEFORE the bscreen check.
    # bscreen is the 2x video mode buffer — NOT exposed on MiSTer (no UI
    # to select 2x mode), so the !bscreen fast-path covers most frames.
    # Keep stock bscreen path as a fallback in case a future feature
    # exposes 2x mode.
    #
    # ALSO gated on bytes_per_pixel != 1 (added 2026-05-23 after ATOV
    # black-screen-with-audio regression on 4086). 8-bit palette-indexed
    # PAKs (ATOV is the canonical case: no data/video.txt, falls back to
    # 4086 stock PIXEL_8 default) lack a palette argument to pass to
    # WriteFrame. WriteFrame's bpp==8 branch requires `palette != NULL`
    # (native_video_writer.c:155) — passing NULL is a silent no-op:
    # nothing reaches DDR3, screen stays black, audio thread plays
    # normally because audio is independent of video.
    #
    # Fix: skip direct-write for 8-bit screens; fall through to the
    # stock SDL chain (memcpy + SDL_Flip -> DUMMY_UpdateRects ->
    # mister_present). mister_present (patch_sdl_dummy.py:108) has a
    # proper bpp==8 branch that reads screen->format->palette from the
    # SDL_Surface (which 4086 maintains via SDL_SetSurfacePalette in
    # sdl/video.c line 238). Direct-write fast-path stays active for
    # 16-bit (Aliens Clash etc.) and 32-bit (modern PAKs) screens; 8-bit
    # PAKs lose the fps gain but ATOV runs natively on 4086 at full
    # framerate anyway (legacy-era target — no perf headroom needed).
    vid = strict_replace(
        vid,
        '\tif(!width || !height) return 0;\n'
        '\th = height;\n'
        '\n'
        '\tif(bscreen)',
        '\tif(!width || !height) return 0;\n'
        '\th = height;\n'
        '\n'
        '#ifdef MISTER_NATIVE_VIDEO\n'
        '\t/* Direct DDR3 write -- bypass SDL 1.2 surface chain (memcpy +\n'
        '\t * SDL_BlitSurface + SDL_Flip -> DUMMY_UpdateRects -> mister_present).\n'
        '\t * WriteFrame does anisotropic NN squish src WxH -> 320x224 Sega CD\n'
        '\t * V28 NTSC. Architectural parity with 7533 (2026-05-22). 2x video\n'
        '\t * mode (bscreen) is NOT exposed on MiSTer; stock path kept as\n'
        '\t * fallback. SDL_framerateDelay() preserved per engine-function-\n'
        '\t * replacement meta-rule (engine framerate cap is a side-effect we\n'
        '\t * mirror; other SDL_* calls are framework calls safe to bypass).\n'
        '\t *\n'
        '\t * Gated on bytes_per_pixel != 1 (2026-05-23 ATOV black-screen fix):\n'
        '\t * 8-bit palette-indexed PAKs (no data/video.txt or ColourDepth 8bit)\n'
        '\t * fall through to stock SDL chain. WriteFrame would no-op on bpp=8\n'
        '\t * with NULL palette; mister_present has bpp=8 palette-lookup via\n'
        '\t * screen->format->palette. */\n'
        '\tif (!bscreen && bytes_per_pixel != 1) {\n'
        '\t\tNativeVideoWriter_WriteFrame(src->data, src->width, src->height,\n'
        '\t\t                              src->width * bytes_per_pixel,\n'
        '\t\t                              bytes_per_pixel * 8,\n'
        '\t\t                              NULL);\n'
        '#if WIN || LINUX\n'
        '\t\tSDL_framerateDelay(&framerate_manager);\n'
        '#endif\n'
        '\t\treturn 1;\n'
        '\t}\n'
        '#endif\n'
        '\n'
        '\tif(bscreen)',
        'sdl/video.c video_copy_screen direct-write fast path (gated on bytes_per_pixel != 1)'
    )

    write(vid_path, vid)
    print("  SDL 1.2 compat stubs + direct-write fast path injected.")

    # ── 4. Patch sdl/control.c — replace control_update() ────────────
    print("Patching sdl/control.c (input mapping)...")
    src = read(os.path.join(obor, 'sdl/control.c'))

    # Add include
    src = strict_replace(
        src,
        '#include "openbor.h"',
        '#include "openbor.h"\n#ifdef MISTER_NATIVE_VIDEO\n#include "native_video_writer.h"\n#endif',
        'sdl/control.c include native_video_writer.h'
    )

    src = replace_function(src, "void control_update(s_playercontrols ** playercontrols, int numplayers)", "control_patch.c", patches)
    write(os.path.join(obor, 'sdl/control.c'), src)
    print("  control_update() replaced.")

    # ── 5. Patch sdl/sdlport.c — replace main() ─────────────────────
    print("Patching sdl/sdlport.c (main + NativeVideoWriter init)...")
    src = read(os.path.join(obor, 'sdl/sdlport.c'))

    # Add includes
    src = strict_replace(
        src,
        '#include "menu.h"',
        '#include "menu.h"\n#ifdef MISTER_NATIVE_VIDEO\n#include "native_video_writer.h"\n#include "native_audio_writer.h"\n#include <sys/stat.h>\n#include <stdlib.h>\n#include <time.h>\n#include <unistd.h>\n#include <pthread.h>\n#include <signal.h>\n#include <execinfo.h>\n#endif',
        'sdl/sdlport.c include native_video_writer.h + helpers'
    )

    # Replace main() and inject any code above it (swap thread, etc.)
    main_sig = "int main(int argc, char *argv[])"
    start = src.find(main_sig)
    if start >= 0:
        patch = read(os.path.join(patches, 'sdlport_patch.c'))
        # Find the first #ifdef MISTER_NATIVE_VIDEO before main() —
        # that's where our pre-main code starts (swap thread, globals)
        premain_marker = "#ifdef MISTER_NATIVE_VIDEO\n/* Crash handler"
        premain_start = patch.find(premain_marker)
        if premain_start >= 0:
            replacement = patch[premain_start:]
        else:
            func_start = patch.find(main_sig)
            replacement = patch[func_start:]
        src = src[:start] + replacement + "\n"

    write(os.path.join(obor, 'sdl/sdlport.c'), src)
    print("  main() replaced.")

    # ── 6. Patch source/utils.c — redirect save + log paths ─────────────
    print("Patching source/utils.c (save path redirect + log path absolute)...")
    src = read(os.path.join(obor, 'source/utils.c'))

    old_macro = '#define COPY_ROOT_PATH(buf, name) strncpy(buf, "./", 2); strncat(buf, name, strlen(name)); strncat(buf, "/", 1);'

    # Note: Logs path is /media/fat/logs/OpenBOR_4086/ — per-build, matching
    # the saves/savestates per-build pattern (sister cores share PAK content
    # at games/OpenBOR/Paks/ but write to separate save/savestate/log dirs
    # because the data is build-specific). This prevents cross-build log
    # mixing when both binaries dispatch under the unified "OpenBOR" setname.
    new_macro = """#ifdef MISTER_NATIVE_VIDEO
#define COPY_ROOT_PATH(buf, name) \\
    do { \\
        if (strcmp(name, "Saves") == 0) { \\
            strcpy(buf, "/media/fat/saves/OpenBOR_4086/"); \\
        } else if (strcmp(name, "SaveStates") == 0) { \\
            strcpy(buf, "/media/fat/savestates/OpenBOR_4086/"); \\
        } else if (strcmp(name, "Config") == 0) { \\
            strcpy(buf, "/media/fat/config/"); \\
        } else if (strcmp(name, "Logs") == 0) { \\
            strcpy(buf, "/media/fat/logs/OpenBOR_4086/"); \\
        } else { \\
            strncpy(buf, "./", 2); strncat(buf, name, strlen(name)); strncat(buf, "/", 1); \\
        } \\
    } while(0)
#else
#define COPY_ROOT_PATH(buf, name) strncpy(buf, "./", 2); strncat(buf, name, strlen(name)); strncat(buf, "/", 1);
#endif"""

    src = strict_replace(src, old_macro, new_macro,
                         'source/utils.c COPY_ROOT_PATH macro (Saves/Config/SaveStates/Logs redirect)')

    # Patch the four LOGFILE macros that hardcode "./Logs/OpenBorLog.txt"
    # and "./Logs/ScriptLog.txt" relative paths. These are used by the
    # engine's writeToLogFile() unconditionally (NOT via COPY_ROOT_PATH),
    # so they need their own replacement. Writing to cwd's Logs/ directory
    # violates the canonical single-location log rule
    # (/media/fat/logs/{CoreName}/) — patch to absolute paths.
    src = strict_replace(
        src,
        '"./Logs/OpenBorLog.txt"',
        '"/media/fat/logs/OpenBOR_4086/OpenBorLog.txt"',
        'source/utils.c LOGFILE OpenBorLog.txt absolute path'
    )
    src = strict_replace(
        src,
        '"./Logs/ScriptLog.txt"',
        '"/media/fat/logs/OpenBOR_4086/ScriptLog.txt"',
        'source/utils.c LOGFILE ScriptLog.txt absolute path'
    )

    write(os.path.join(obor, 'source/utils.c'), src)
    print("  Save path redirected; log path absolute (/media/fat/logs/OpenBOR_4086/).")

    # ── 6c. Patch openbor.c — route .cfg/.hi to Config, .s00 to SaveStates ──
    print("Patching openbor.c (split save directories)...")
    obor_c = read(os.path.join(obor, 'openbor.c'))

    # .cfg files: savesettings/loadsettings -> "Config"
    # These have: getBasePath(path, "Saves", 0); getPakName(tmpname, 4);
    obor_c = strict_replace(
        obor_c,
        'getBasePath(path, "Saves", 0);\n    getPakName(tmpname, 4);',
        '#ifdef MISTER_NATIVE_VIDEO\n    getBasePath(path, "Config", 0);\n#else\n    getBasePath(path, "Saves", 0);\n#endif\n    getPakName(tmpname, 4);',
        'openbor.c getBasePath Saves -> Config (.cfg getPakName 4)'
    )

    # default.cfg: saveasdefault/loadfromdefault -> "Config"
    # These have: getBasePath(path, "Saves", 0); strncat(path, "default.cfg", 128);
    obor_c = strict_replace(
        obor_c,
        'getBasePath(path, "Saves", 0);\n    strncat(path, "default.cfg", 128);',
        '#ifdef MISTER_NATIVE_VIDEO\n    getBasePath(path, "Config", 0);\n#else\n    getBasePath(path, "Saves", 0);\n#endif\n    strncat(path, "default.cfg", 128);',
        'openbor.c getBasePath Saves -> Config (default.cfg)'
    )

    # .hi files: saveHighScoreFile/loadHighScoreFile -> "Config"
    # These have: getBasePath(path, "Saves", 0); getPakName(tmpname, 1);
    obor_c = strict_replace(
        obor_c,
        'getBasePath(path, "Saves", 0);\n    getPakName(tmpname, 1);',
        '#ifdef MISTER_NATIVE_VIDEO\n    getBasePath(path, "Config", 0);\n#else\n    getBasePath(path, "Saves", 0);\n#endif\n    getPakName(tmpname, 1);',
        'openbor.c getBasePath Saves -> Config (.hi getPakName 1)'
    )

    # .s00 save states: saveScriptFile/loadScriptFile -> "SaveStates"
    # These have: getBasePath(path, "Saves", 0); getPakName(tmpvalue, 2);//.scr
    obor_c = strict_replace(
        obor_c,
        'getBasePath(path, "Saves", 0);\n    getPakName(tmpvalue, 2);//.scr',
        '#ifdef MISTER_NATIVE_VIDEO\n    getBasePath(path, "SaveStates", 0);\n#else\n    getBasePath(path, "Saves", 0);\n#endif\n    getPakName(tmpvalue, 2);//.scr',
        'openbor.c getBasePath Saves -> SaveStates (.scr getPakName 2 tmpvalue)'
    )
    # loadScriptFile uses tmpname instead of tmpvalue
    obor_c = strict_replace(
        obor_c,
        'getBasePath(path, "Saves", 0);\n    getPakName(tmpname, 2);//.scr',
        '#ifdef MISTER_NATIVE_VIDEO\n    getBasePath(path, "SaveStates", 0);\n#else\n    getBasePath(path, "Saves", 0);\n#endif\n    getPakName(tmpname, 2);//.scr',
        'openbor.c getBasePath Saves -> SaveStates (.scr getPakName 2 tmpname)'
    )

    write(os.path.join(obor, 'openbor.c'), obor_c)
    print("  .cfg/.hi -> /media/fat/config/, .s00 -> /media/fat/savestates/OpenBOR_4086/")

    # ── 6b. Patch logsDir default to /media/fat/logs/OpenBOR_4086 ────
    # logsDir is declared in sdl/sdlport.c as: char logsDir[128] = {"Logs"};
    print("Patching logsDir default in sdl/sdlport.c...")
    sdlport = read(os.path.join(obor, 'sdl/sdlport.c'))
    logs_old = 'char logsDir[128] = {"Logs"};'
    logs_new = '#ifdef MISTER_NATIVE_VIDEO\nchar logsDir[128] = {"/media/fat/logs/OpenBOR_4086"};\n#else\nchar logsDir[128] = {"Logs"};\n#endif'
    if logs_old in sdlport:
        sdlport = sdlport.replace(logs_old, logs_new, 1)
        write(os.path.join(obor, 'sdl/sdlport.c'), sdlport)
        print("  logsDir default changed to /media/fat/logs/OpenBOR_4086")
    else:
        print("  WARN: logsDir pattern not found in sdl/sdlport.c")

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

    # -- Keep native PIXEL_8 default.
    # PIXEL_32 causes NULL pointer crash at address 0xe4 during model
    # loading — OpenBOR structs aren't initialized in 32bpp path.
    # 8bpp works for all PAKs. Colors may use shared palette but no crashes.
    # PAKs with data/video.txt still override to their own format.
    print("  Keeping native PIXEL_8 default (all PAKs work, no crashes).")

    write(pf_path, pf)
    print(f"  {applied}/{len(fixes)} blend R/B fixes applied.")

    # ── 10. Audio Stage 1: NO PATCH (Option C v2, 2026-05-15 evening).
    #
    # Engine runs at UPSTREAM NATIVE 44.1 kHz (Sega CD Red Book CDDA rate).
    # Sample reads use upstream FIX_TO_INT(fp_pos) nearest-neighbor.
    # Our sblaster_patch.c glue layer handles 44.1 -> 48 kHz conversion via
    # linear interpolation before DDR3 submission — same architectural
    # pattern as PICO-8. Matches the NTSC-region-match rule.
    #
    # HISTORY:
    #   2026-05-15 (morning): force-48-kHz patch (Option A) killed pitch
    #     shift but diverged from Sega CD's native rate.
    #   2026-05-15 (afternoon): Option C v1 cubic Hermite failed with
    #     "constant per Stage 2 tick" buzz.
    #   2026-05-15 (evening): Option C v2 — engine at 44.1k native, LINEAR
    #     resample in glue. Force-48-kHz patch REMOVED.
    print("Step 10 (audio): mixaudio() soundcache-reload fix (mirror from 7533)")
    print("                  Fixes heavy-scene silent cutout + sudden-loud buzz on voice reactivation.")
    sm_path = os.path.join(obor, 'source/gamelib/soundmix.c')
    sm = read(sm_path)

    # FIX for task #10 (heavy-scene silent cutout + buzz on resume).
    #
    # Root cause: upstream 4086's mixaudio() has the same defensive NULL-check
    # as 7533 — when soundcache eviction frees a sample mid-playback, the
    # voice gets PERMANENTLY deactivated:
    #     if(!soundcache[snum].sample.sampleptr) {
    #         vchannel[chan].active = 0;
    #         continue;
    #     }
    # On heavy-scene PAKs (e.g. MvC-style, ATOV boss fights), eviction
    # cascades -> all voices deactivated -> engine emits silence. When a
    # NEW audio event later triggers reload, sudden large samples can
    # produce audible buzz/click on resume.
    #
    # Fix: lazy-reload evicted samples via sound_reload_sample() before
    # deactivating. Only deactivate if reload also fails. Matches the
    # 7533 fix exactly; 4086 upstream already has sound_reload_sample
    # defined at line ~330 (same code path).
    #
    # NOTE: 4086 upstream's mix multipliers are already at unity
    # (lmusic * lvolume / MAXVOLUME, no * 2.5 or * 1.5 boost like 7533
    # added). So we DON'T mirror the 7533 multiplier-revert here — there's
    # nothing to revert.
    #
    # HISTORY: previously this step was a dead-fire-in-hotpath diagnostic
    # logger (fprintf + fflush per silent-window transition) that may
    # have contributed to the user-reported "silence then loud buzz" by
    # causing SD-card I/O storms -> ring buffer underruns. Removing it
    # AND applying the real fix in one commit.
    OLD_NULL_CHECK = (
        '            if(!soundcache[snum].sample.sampleptr)\n'
        '            {\n'
        '                vchannel[chan].active = 0;\n'
        '                continue;\n'
        '            }\n'
    )
    NEW_NULL_CHECK = (
        '            if(!soundcache[snum].sample.sampleptr)\n'
        '            {\n'
        '                /* MiSTer Frontier task #10 fix (mirror of 7533):\n'
        '                 * lazy-reload evicted samples before deactivating.\n'
        '                 * Upstream eviction caused MvC heavy-scene cutout +\n'
        '                 * post-silence buzz on resume.\n'
        '                 * sound_reload_sample() reloads from packfile. */\n'
        '                sound_reload_sample(snum);\n'
        '                if(!soundcache[snum].sample.sampleptr)\n'
        '                {\n'
        '                    vchannel[chan].active = 0;\n'
        '                    continue;\n'
        '                }\n'
        '            }\n'
    )
    sm = strict_replace(sm, OLD_NULL_CHECK, NEW_NULL_CHECK,
                        'soundmix.c mixaudio NULL-check soundcache-reload')

    write(sm_path, sm)
    print("  soundmix.c patched (mixaudio cache-reload, NO diagnostic).")

    print("\nAll patches applied successfully.")

if __name__ == '__main__':
    main()
