/*
 * headless_patch.c — OpenBOR Build 4086 diff/debug-harness replacement main().
 *
 * The SDL 1.2 sister of MiSTer_OpenBOR_7533/patches/headless_patch.c. Applied
 * ONLY by .github/scripts/apply_patches_headless.py for the diff_harness build
 * (native x86, no MiSTer/DDR3). NOT the ship build (build_mister_arm.sh).
 *
 * Loads a PAK from env OB_PAK, runs it headless (SDL 1.2 dummy video/audio),
 * and lets video_copy_screen() (patched by apply_patches_headless.py) count
 * frames and exit cleanly after OB_FRAMES. Crash (SIGSEGV/BUS/ABRT/FPE) and
 * hang (SIGALRM, armed/re-armed per frame) handlers dump a backtrace whose
 * offsets resolve via addr2line -e OpenBOR.elf <addr> to exact file:line.
 *
 * The whole content of this file replaces the upstream main() in place, so the
 * engine globals (packfile, paksDir, savesDir, logsDir, screenShotsDir) +
 * functions (setSystemRam, initSDL, packfile_mode, dirExists, openborMain,
 * borExit) — all declared earlier in sdlport.c — are already visible.
 *
 * Build 4086 predates the .inp input recorder, so the AI bot here is
 * injection-only (menu navigation + scripted in-level moves); there is no
 * record/replay. We skip 4086's Menu() (the PAK browser) and set packfile from
 * OB_PAK directly, the same way the 7533 headless main does.
 */
#include <signal.h>
#include <execinfo.h>
#include <unistd.h>
#include <stdlib.h>

long hl_alarm_secs = 30;   /* re-armed each frame by patched video_copy_screen() */

static void hl_backtrace(const char *tag)
{
    void *bt[48];
    int n = backtrace(bt, 48);
    fprintf(stderr, "\n[headless] %s -- backtrace (%d frames):\n", tag, n);
    fflush(stderr);
    backtrace_symbols_fd(bt, n, 2);
}

static void hl_crash_handler(int sig)
{
    fprintf(stderr, "\n[headless] CRASH signal %d\n", sig);
    hl_backtrace("crash");
    _exit(139);
}

static void hl_alarm_handler(int sig)
{
    (void)sig;
    fprintf(stderr, "\n[headless] HANG: no frame within %ld s (wall-clock alarm)\n",
            hl_alarm_secs);
    hl_backtrace("hang");
    _exit(98);
}

int main(int argc, char *argv[])
{
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);

    signal(SIGSEGV, hl_crash_handler);
    signal(SIGBUS,  hl_crash_handler);
    signal(SIGABRT, hl_crash_handler);
    signal(SIGFPE,  hl_crash_handler);
    signal(SIGALRM, hl_alarm_handler);
    { const char *e = getenv("OB_ALARM"); if (e) hl_alarm_secs = atol(e); }

    /* headless SDL 1.2: no window, no audio device */
    setenv("SDL_VIDEODRIVER", "dummy", 1);
    setenv("SDL_AUDIODRIVER", "dummy", 1);

    setSystemRam();
    initSDL();
    packfile_mode(0);
    dirExists(paksDir, 1);
    dirExists(savesDir, 1);
    dirExists(logsDir, 1);
    dirExists(screenShotsDir, 1);

    {
        const char *pak = getenv("OB_PAK");
        if (!pak || !*pak) {
            fprintf(stderr, "[headless] OB_PAK not set -- nothing to load\n");
            return 2;
        }
        strncpy(packfile, pak, sizeof(packfile) - 1);
        packfile[sizeof(packfile) - 1] = 0;
        fprintf(stderr, "[headless] PAK: %s\n", packfile);
    }

    alarm((unsigned)hl_alarm_secs);   /* covers load + first frame */

    fprintf(stderr, "[headless] entering openborMain()...\n");
    openborMain(argc, argv);
    fprintf(stderr, "[headless] openborMain() returned\n");
    borExit(0);
    return 0;
}
