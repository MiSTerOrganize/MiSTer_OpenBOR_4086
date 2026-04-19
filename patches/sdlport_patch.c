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
 *   #include <time.h>
 *   #include <unistd.h>
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
    /* Saves redirected to /media/fat/saves/OpenBOR_4086/ in utils.c.
     * Logs redirected out of games directory entirely. */
    strncpy(logsDir, "/media/fat/logs/OpenBOR_4086/", sizeof(logsDir) - 1);
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
    #define MISTER_F0_PATH   "/media/fat/config/OpenBOR_4086.f0"
    {
        /* OpenBOR PAKs are 50-150+ MB — too large for the 256 KB DDR3
         * cart buffer. Instead of streaming data through DDR3, we read
         * the FILE PATH that MiSTer writes to .f0 when user picks a
         * PAK from the OSD, then load that file directly from SD.
         *
         * Flow: user picks PAK in OSD → MiSTer writes path to .f0 →
         * ARM polls for .f0 → reads path → deletes .f0 → OpenBOR
         * loads PAK from SD path. No DDR3 size limit. */

        /* 1) Check for Reset Pak cache (in /tmp, survives exit+relaunch) */
        struct stat st;
        if (stat(MISTER_PAK_CACHE, &st) == 0 && st.st_size > 0) {
            strncpy(packfile, MISTER_PAK_CACHE, sizeof(packfile) - 1);
            packfile[sizeof(packfile) - 1] = 0;
            fprintf(stderr, "MiSTer: Reset Pak cache found: %s (%ld bytes)\n",
                    packfile, (long)st.st_size);
        }
        /* 2) Poll for .f0 (MiSTer creates it when user picks from OSD) */
        else {
            char f0_path[256] = {0};

            fprintf(stderr, "MiSTer: waiting for OSD PAK selection (.f0)...\n");
            while (1) {
                FILE *f = fopen(MISTER_F0_PATH, "r");
                if (f) {
                    if (fgets(f0_path, sizeof(f0_path), f)) {
                        char *nl = strchr(f0_path, '\n');
                        if (nl) *nl = 0;
                        char *cr = strchr(f0_path, '\r');
                        if (cr) *cr = 0;
                    }
                    fclose(f);
                    if (strlen(f0_path) > 0) {
                        /* Build absolute path and set as packfile */
                        snprintf(packfile, sizeof(packfile), "/media/fat/%s", f0_path);
                        remove(MISTER_F0_PATH);
                        fprintf(stderr, "MiSTer: OSD selected: %s\n", packfile);
                        break;
                    }
                }
                usleep(200000);  /* poll every 200ms */
            }
        }
    }
#else
    Menu();
#endif

#ifndef SKIP_CODE
    getPakName(pakname, -1);
    video_set_window_title(pakname);
#endif
    fprintf(stderr, "MiSTer: entering openborMain()...\n");
    openborMain(argc, argv);
    fprintf(stderr, "MiSTer: openborMain() returned normally\n");

#ifdef MISTER_NATIVE_VIDEO
    NativeVideoWriter_Shutdown();
    NativeAudioWriter_Shutdown();
#endif

    borExit(0);
    return 0;
}
