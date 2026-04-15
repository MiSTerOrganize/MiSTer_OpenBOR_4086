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
    mkdir("/media/fat/saves/OpenBOR", 0755);
#endif

    packfile_mode(0);
#ifdef ANDROID
    dirExists(rootDir, 1);
    chdir(rootDir);
#endif
    dirExists(paksDir, 1);
#ifdef MISTER_NATIVE_VIDEO
    /* Saves go to /media/fat/saves/OpenBOR/ (redirected in utils.c).
     * ScreenShots not used (no button mapped to FLAG_SCREENSHOT).
     * Don't create local Saves/ or ScreenShots/ folders. */
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
    {
        /* Check if a PAK was loaded via MiSTer OSD file browser.
         * If so, write it to a temp file and skip the PAK browser menu. */
        uint32_t pak_size = NativeVideoWriter_CheckCart();
        if (pak_size > 0) {
            void *pak_buf = malloc(pak_size);
            if (pak_buf) {
                uint32_t bytes_read = NativeVideoWriter_ReadCart(pak_buf, pak_size);
                if (bytes_read > 0) {
                    FILE *f = fopen("/tmp/openbor_osd.pak", "wb");
                    if (f) {
                        fwrite(pak_buf, 1, bytes_read, f);
                        fclose(f);
                        strcpy(packfile, "/tmp/openbor_osd.pak");
                        NativeVideoWriter_AckCart();
                        fprintf(stderr, "MiSTer OSD: loaded PAK (%u bytes)\n", bytes_read);
                    }
                }
                free(pak_buf);
            }
        }

        /* If no OSD PAK, check for restart file from Reset Pak */
        if (strcmp(packfile, "/tmp/openbor_osd.pak") != 0) {
            FILE *rf = fopen("/tmp/openbor_restart.pak", "r");
            if (rf) {
                char restart_pak[128] = {0};
                if (fgets(restart_pak, sizeof(restart_pak), rf)) {
                    char *nl = strchr(restart_pak, '\n');
                    if (nl) *nl = 0;
                    if (strlen(restart_pak) > 0) {
                        strncpy(packfile, restart_pak, sizeof(packfile) - 1);
                        fprintf(stderr, "MiSTer: Restarting PAK: %s\n", packfile);
                    }
                }
                fclose(rf);
                remove("/tmp/openbor_restart.pak");
            } else {
                /* No OSD PAK, no restart — show PAK browser */
                Menu();
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
    openborMain(argc, argv);

#ifdef MISTER_NATIVE_VIDEO
    NativeVideoWriter_Shutdown();
    NativeAudioWriter_Shutdown();
#endif

    borExit(0);
    return 0;
}
