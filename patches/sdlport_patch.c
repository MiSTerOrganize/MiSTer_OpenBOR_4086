/*
 * MiSTer_OpenBOR — sdlport.c Patch
 *
 * Adds NativeVideoWriter initialization, save directory creation,
 * and OSD PAK loading support to OpenBOR's main() function.
 *
 * PATCH: In sdl/sdlport.c, replace the entire main() function
 * (line 52 through line 118) with the version below.
 *
 * Also add these includes at the top of the file, after the existing includes:
 *
 *   #ifdef MISTER_NATIVE_VIDEO
 *   #include "native_video_writer.h"
 *   #include "native_audio_writer.h"
 *   #include <sys/stat.h>
 *   #include <stdlib.h>
 *   #endif
 *
 * Copyright (C) 2026 MiSTer Organize -- GPL-3.0
 */

int main(int argc, char *argv[])
{
#ifndef SKIP_CODE
    char pakname[256];
#endif
#ifdef CUSTOM_SIGNAL_HANDLER
    struct sigaction sigact;
#endif

#ifdef DARWIN
    char resourcePath[PATH_MAX];
    CFBundleRef mainBundle;
    CFURLRef resourcesDirectoryURL;
    mainBundle = CFBundleGetMainBundle();
    resourcesDirectoryURL = CFBundleCopyResourcesDirectoryURL(mainBundle);
    if(!CFURLGetFileSystemRepresentation(resourcesDirectoryURL, true, (UInt8 *) resourcePath, PATH_MAX))
    {
        borExit(0);
    }
    CFRelease(resourcesDirectoryURL);
    chdir(resourcePath);
#elif WII
    fatInitDefault();
#endif

#ifdef CUSTOM_SIGNAL_HANDLER
    sigact.sa_sigaction = handleFatalSignal;
    sigact.sa_flags = SA_RESTART | SA_SIGINFO;

    if(sigaction(SIGSEGV, &sigact, NULL) != 0)
    {
        printf("Error setting signal handler for %d (%s)\n", SIGSEGV, strsignal(SIGSEGV));
        exit(EXIT_FAILURE);
    }
#endif

#ifdef MISTER_NATIVE_VIDEO
    /* Disable SDL's audio + video subsystems entirely. The FPGA drives
     * both via DDR3 ring buffers; SDL just provides timers/threads/events. */
    setenv("SDL_VIDEODRIVER", "dummy",  1);
    setenv("SDL_AUDIODRIVER", "dummy",  1);
#endif

    setSystemRam();
    initSDL();

#ifdef MISTER_NATIVE_VIDEO
    /* Initialize DDR3 native video writer */
    if (!NativeVideoWriter_Init()) {
        fprintf(stderr, "NativeVideoWriter: init failed, falling back to SDL\n");
    }

    /* Initialize DDR3 native audio writer. sblaster's SB_playstart
     * thread will refuse to start if this fails. */
    if (!NativeAudioWriter_Init()) {
        fprintf(stderr, "NativeAudioWriter: init failed, audio will be silent\n");
    }

    /* Create MiSTer save directory */
    mkdir("/media/fat/saves", 0755);
    mkdir("/media/fat/saves/OpenBOR_4086", 0755);
#endif

    packfile_mode(0);
#ifdef ANDROID
    dirExists(rootDir, 1);
    chdir(rootDir);
#endif
    dirExists(paksDir, 1);
#ifdef MISTER_NATIVE_VIDEO
    /* Saves redirected to /media/fat/saves/OpenBOR_4086/ in utils.c. */
    dirExists(logsDir, 1);
#else
    dirExists(savesDir, 1);
    dirExists(logsDir, 1);
    dirExists(screenShotsDir, 1);
#endif

#ifdef ANDROID
    if(dirExists("/mnt/usbdrive/OpenBOR/Paks", 0))
        strcpy(paksDir, "/mnt/usbdrive/OpenBOR/Paks");
    else if(dirExists("/usbdrive/OpenBOR/Paks", 0))
        strcpy(paksDir, "/usbdrive/OpenBOR/Paks");
    else if(dirExists("/mnt/extsdcard/OpenBOR/Paks", 0))
        strcpy(paksDir, "/mnt/extsdcard/OpenBOR/Paks");
#endif

#ifdef MISTER_NATIVE_VIDEO
    /* Cart cache lives on tmpfs (/tmp). This is critical for load
     * speed: OpenBOR reads the PAK every time it starts, so the cache
     * has to be in RAM -- reading a 100+ MB PAK off SD takes minutes.
     * /tmp survives the Reset Pak exit+relaunch cycle (same Linux
     * session), and is cleared on reboot which is the right behaviour
     * -- after a reboot the user will re-pick through MiSTer's OSD,
     * the cart will stream via ioctl into DDR3, and we cache it here
     * fresh. */
    #define MISTER_PAK_CACHE "/tmp/openbor_current.pak"
    {
        /* 1) Fresh OSD cart? Overwrite the cache. */
        uint32_t pak_size = NativeVideoWriter_CheckCart();
        if (pak_size > 0) {
            void *pak_buf = malloc(pak_size);
            if (pak_buf) {
                uint32_t bytes_read = NativeVideoWriter_ReadCart(pak_buf, pak_size);
                if (bytes_read > 0) {
                    FILE *f = fopen(MISTER_PAK_CACHE, "wb");
                    if (f) {
                        fwrite(pak_buf, 1, bytes_read, f);
                        fclose(f);
                        fprintf(stderr, "MiSTer OSD: cached PAK (%u bytes) at %s\n",
                                bytes_read, MISTER_PAK_CACHE);
                    }
                }
                free(pak_buf);
                NativeVideoWriter_AckCart();
            }
        }

        /* 2) Pick the next PAK to play. Priority:
         *    - Cached file from OSD / previous session (covers fresh
         *      load AND Reset Pak restart).
         *    - Otherwise fall back to OpenBOR's builtin PAK browser.
         * The Quit action in the pause menu deletes the cache before
         * exiting, so Quit -> relaunch lands on Menu() instead of
         * replaying the same PAK. */
        struct stat st;
        if (stat(MISTER_PAK_CACHE, &st) == 0 && st.st_size > 0) {
            strncpy(packfile, MISTER_PAK_CACHE, sizeof(packfile) - 1);
            packfile[sizeof(packfile) - 1] = 0;
            fprintf(stderr, "MiSTer: loading PAK %s (%ld bytes)\n",
                    packfile, (long)st.st_size);
        } else {
            fprintf(stderr, "MiSTer: no cached PAK, opening builtin browser\n");
            Menu();
        }
    }
#else
    Menu();
#endif

#ifndef SKIP_CODE
    getPakName(pakname, -1);
    video_set_window_title(pakname);
#endif
    openborMain(argc, argv);

#ifdef MISTER_NATIVE_VIDEO
    NativeVideoWriter_Shutdown();
    NativeAudioWriter_Shutdown();
#endif

    borExit(0);
    return 0;
}
