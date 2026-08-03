#!/usr/bin/env python3
"""apply_patches_headless.py — Build 4086 headless diff/debug-harness patcher.

The SDL 1.2 sister of MiSTer_OpenBOR_7533/.github/scripts/apply_patches_headless.py.
SEPARATE from apply_patches.py (the MiSTer ship build). Applies only the harness
hooks needed to run PAKs off-device (native x86, no SDL window / no MiSTer/DDR3):

  1. sdl/sdlport.c : replace main() with the headless main (env OB_PAK, crash +
     SIGALRM-hang handlers, SDL 1.2 dummy) from patches/headless_patch.c.
  2. sdl/video.c   : per-frame counter + exit-after-OB_FRAMES + alarm re-arm in
     video_copy_screen (so a PAK runs N frames then exits clean; a stuck frame
     trips SIGALRM).
  3. openbor.c     : two-phase scripted-input injection (the AI bot) in
     inputrefresh(). Build 4086 predates the .inp recorder, so the bot is
     injection-only (menu navigation + scripted in-level moves) — no
     record/replay. Unset OB_INPUT/OB_INPUT2 => NO-OP (control path unchanged).

Build 4086 FLAG_* bits differ from 7533: ESC=0x1, START=0x2, MOVELEFT=0x4,
MOVERIGHT=0x8, MOVEUP=0x10, MOVEDOWN=0x20, ATTACK=0x40, JUMP=0x80, SPECIAL=0x100.
keyflags is u32. C89-safe (declarations first in every block).

Usage: apply_patches_headless.py <openbor_engine_dir> <patches_dir>
"""
import sys, os

def read(p):
    with open(p, "r", encoding="utf-8", errors="surrogateescape") as f:
        return f.read()

def write(p, c):
    with open(p, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(c)

def extract_function(source, func_sig):
    start = source.find(func_sig)
    if start < 0:
        return None, -1, -1
    brace = 0; found_open = False; end = start
    for i in range(start, len(source)):
        if source[i] == '{':
            brace += 1; found_open = True
        elif source[i] == '}':
            brace -= 1
        if found_open and brace == 0:
            end = i + 1; break
    return source[start:end], start, end

def strict_replace(content, old, new, label, count=1):
    if old not in content:
        raise RuntimeError(f"strict_replace failed for '{label}': pattern not found.\n"
                           f"  expected: {old[:80]!r}")
    n = content.count(old)
    if n != count:
        raise RuntimeError(f"strict_replace failed for '{label}': expected {count}, found {n}.")
    return content.replace(old, new)

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <openbor_dir> <patches_dir>")
        sys.exit(1)
    obor, patches = sys.argv[1], sys.argv[2]

    # ── 0. Add a BUILD_HEADLESS Makefile target (distro SDL 1.2, native arch) ─
    # The stock BUILD_LINUX target drags in OpenGL + SDKPATH-based include/lib
    # paths unfit for a headless distro build (and defaults to -m32); the ship
    # BUILD_MISTER target is DDR3/ARM. So add a dedicated headless target: distro
    # SDL 1.2, no OpenGL, with ARCHFLAGS + the lib dir (HL_LIBDIR) passed on the
    # make command line (x86-64 or arm32). -fcommon + -Wno-error for the
    # 2015-era source on a modern gcc; -g/-rdynamic/-funwind-tables for the
    # crash-backtrace handler.
    print("Patching Makefile (BUILD_HEADLESS target)...")
    mf_path = os.path.join(obor, "Makefile")
    mf = read(mf_path)
    hl_target = """
ifdef BUILD_HEADLESS
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
INCLUDES        = /usr/include /usr/include/SDL
LIBRARIES       = $(HL_LIBDIR)
endif
"""
    marker = "ifeq ($(BUILD_OPENDINGUX), 0)\nBUILD_DEBUG     = 1\nendif\nendif"
    mf = strict_replace(mf, marker, marker + "\n" + hl_target,
                        "Makefile BUILD_HEADLESS target (after BUILD_OPENDINGUX)")
    mf = strict_replace(mf,
        "ifdef BUILD_SDL\nCFLAGS \t       += -DSDL\nendif",
        "ifdef BUILD_SDL\nCFLAGS \t       += -DSDL\nendif\n\n\nifdef BUILD_HEADLESS\nCFLAGS         += -fcommon -Wno-error -g -rdynamic -funwind-tables -fasynchronous-unwind-tables\nendif",
        "Makefile BUILD_HEADLESS CFLAGS")
    write(mf_path, mf)
    print("  BUILD_HEADLESS Makefile target added.")

    # ── 1. Replace main() in sdl/sdlport.c with the headless main ──────
    print("Patching sdl/sdlport.c (headless main)...")
    sp_path = os.path.join(obor, "sdl/sdlport.c")
    sp = read(sp_path)
    sig = "int main(int argc, char *argv[])"
    _, start, end = extract_function(sp, sig)
    if start < 0:
        raise RuntimeError(f"could not find '{sig}' in sdl/sdlport.c")
    patch = read(os.path.join(patches, "headless_patch.c"))
    pstart = patch.find("#include <signal.h>")
    if pstart < 0:
        raise RuntimeError("headless_patch.c missing expected header marker")
    sp = sp[:start] + patch[pstart:] + sp[end:]
    write(sp_path, sp)
    print("  main() replaced with headless main.")

    # ── 2. Frame counter + exit + alarm re-arm in video_copy_screen ────
    print("Patching sdl/video.c (headless frame counter + hang re-arm)...")
    v_path = os.path.join(obor, "sdl/video.c")
    v = read(v_path)
    # Insert AFTER the function's local declarations (C89-safe) — the last local
    # in video_copy_screen is `SDL_Rect rectdes, rectsrc;` (tab-indented).
    anchor = "\tSDL_Rect rectdes, rectsrc;"
    repl = ("\tSDL_Rect rectdes, rectsrc;\n"
            "\t{\n"
            "\t\t/* headless harness: per-frame counter + hang re-arm + exit */\n"
            "\t\tstatic long _hl_n = 0, _hl_max = -2, _hl_alarm = -2;\n"
            "\t\tif (_hl_max == -2) { const char *e = getenv(\"OB_FRAMES\"); _hl_max = e ? atol(e) : 120; }\n"
            "\t\tif (_hl_alarm == -2) { const char *e = getenv(\"OB_ALARM\"); _hl_alarm = e ? atol(e) : 30; }\n"
            "\t\tif (_hl_alarm > 0) alarm((unsigned)_hl_alarm);\n"
            "\t\t_hl_n++;\n"
            "\t\tif (_hl_max > 0 && _hl_n >= _hl_max) {\n"
            "\t\t\tfprintf(stderr, \"[headless] reached %ld frames, exiting clean\\n\", _hl_n);\n"
            "\t\t\tfflush(stderr);\n"
            "\t\t\texit(0);\n"
            "\t\t}\n"
            "\t}")
    v = strict_replace(v, anchor, repl, "sdl/video.c headless frame counter")
    if "#include <stdlib.h>" not in v:
        v = "#include <stdlib.h>\n" + v
    if "#include <unistd.h>" not in v:
        v = "#include <unistd.h>\n" + v
    write(v_path, v)
    print("  video_copy_screen frame counter + hang re-arm injected.")

    # ── 3. Two-phase scripted-input injection into inputrefresh (AI bot) ─
    print("Patching openbor.c (headless input injection)...")
    o_path = os.path.join(obor, "openbor.c")
    o = read(o_path)
    inj_anchor = "    control_update(playercontrolpointers, MAX_PLAYERS);"
    inj_code = inj_anchor + """
    /* headless AI bot: two-phase scripted input injection (Build 4086 has no
       .inp recorder, so this is injection-only). A MENU timeline (OB_INPUT)
       drives while level==NULL (indexed by global frame) and auto-stops the
       instant a level loads; an in-level timeline (OB_INPUT2) drives thereafter
       (level-relative frames). Both menus (bothnewkeys) and in-level play
       (player[p].keys) consume playercontrolpointers[0], so one hook drives all.
       Unset => NO-OP. 4086 FLAG_* bits: START=0x2 ESC=0x1 MOVERIGHT=0x8
       MOVEUP=0x10 ATTACK=0x40 JUMP=0x80. keyflags is u32. C89-safe. */
    {
        static int _inj_init = 0, _mn = 0, _ln = 0;
        static long _inj_frame = 0, _lvl_frame = -1;
        static int _lvl_seen = 0;
        static unsigned _mprev = 0, _lprev = 0;
        static unsigned long long _shash = 1469598103934665603ULL;
        static struct { long a, b; unsigned k; } _menu[512], _lvl[512];
        unsigned _want; int _i; long _lf;
        if (!_inj_init) {
            const char *_pm = getenv("OB_INPUT");
            const char *_pl = getenv("OB_INPUT2");
            char _ln2[256]; long _a, _b; unsigned _k; FILE *_f;
            _inj_init = 1;
            if (_pm && (_f = fopen(_pm, "r"))) {
                while (_mn < 512 && fgets(_ln2, sizeof(_ln2), _f))
                    if (_ln2[0] != '#' && sscanf(_ln2, "%ld %ld %x", &_a, &_b, &_k) == 3) {
                        _menu[_mn].a = _a; _menu[_mn].b = _b; _menu[_mn].k = _k; _mn++;
                    }
                fclose(_f);
            }
            if (_pl && (_f = fopen(_pl, "r"))) {
                while (_ln < 512 && fgets(_ln2, sizeof(_ln2), _f))
                    if (_ln2[0] != '#' && sscanf(_ln2, "%ld %ld %x", &_a, &_b, &_k) == 3) {
                        _lvl[_ln].a = _a; _lvl[_ln].b = _b; _lvl[_ln].k = _k; _ln++;
                    }
                fclose(_f);
            }
            if (_mn || _ln) {
                fprintf(stderr, "[inject] menu=%d rows, level=%d rows\\n", _mn, _ln);
                fflush(stderr);
            }
        }
        if (_mn > 0 || _ln > 0) {
            _want = 0;
            if (!level) {
                for (_i = 0; _i < _mn; _i++)
                    if (_inj_frame >= _menu[_i].a && _inj_frame <= _menu[_i].b) _want |= _menu[_i].k;
                playercontrolpointers[0]->keyflags = _want;
                playercontrolpointers[0]->newkeyflags = _want & ~_mprev;
                _mprev = _want;
            } else {
                if (!_lvl_seen) {
                    _lvl_seen = 1; _lvl_frame = _inj_frame;
                    fprintf(stderr, "[inject] entered level at frame %ld\\n", _inj_frame);
                    fflush(stderr);
                }
                _lf = _inj_frame - _lvl_frame;
                for (_i = 0; _i < _ln; _i++)
                    if (_lf >= _lvl[_i].a && _lf <= _lvl[_i].b) _want |= _lvl[_i].k;
                playercontrolpointers[0]->keyflags = _want;
                playercontrolpointers[0]->newkeyflags = _want & ~_lprev;
                _lprev = _want;
                if (player[0].ent) {
                    unsigned int _xb, _yb, _zb;
                    memcpy(&_xb, &player[0].ent->position.x, 4);
                    memcpy(&_yb, &player[0].ent->position.y, 4);
                    memcpy(&_zb, &player[0].ent->position.z, 4);
                    _shash = (_shash ^ _xb) * 1099511628211ULL;
                    _shash = (_shash ^ _yb) * 1099511628211ULL;
                    _shash = (_shash ^ _zb) * 1099511628211ULL;
                    if ((_lf % 20) == 0) {
                        fprintf(stderr, "[state] lf=%ld x=%d y=%d z=%d h=%016llx\\n",
                                _lf, (int)player[0].ent->position.x,
                                (int)player[0].ent->position.y,
                                (int)player[0].ent->position.z, _shash);
                        fflush(stderr);
                    }
                }
            }
            _inj_frame++;
        }
    }"""
    o = strict_replace(o, inj_anchor, inj_code, "openbor.c headless input injection")
    write(o_path, o)
    print("  two-phase input injection hooked into inputrefresh().")

    print("All headless patches applied successfully.")

if __name__ == "__main__":
    main()
