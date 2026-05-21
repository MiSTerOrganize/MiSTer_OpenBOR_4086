#!/usr/bin/env python3
"""
patch_sdl_dummy.py -- inject DDR3-write code into SDL 1.2.15's dummy
video driver so OpenBOR's full SDL render pipeline lands its final
composited frames directly in the FPGA's video ring buffer.

Why we do this instead of intercepting at OpenBOR's video_copy_screen:
The video_copy_screen intercept reads OpenBOR's vscreen, which contains
buggy R/B-swapped pixels for sprites drawn through certain blend
functions in PIXEL_32 mode. By letting OpenBOR's full SDL pipeline run
(memcpy vscreen -> bscreen, then SDL_BlitSurface bscreen -> screen),
SDL's BlitSurface does its own format conversion based on surface
masks. We then read 'screen->pixels' in our patched UpdateRects and
get the same final image that SumolX's fbcon path produces.

The patch:
  1. Adds includes for /dev/mem mmap and our DDR3 layout constants
  2. Initialises the DDR3 mapping in DUMMY_VideoInit
  3. Hooks DUMMY_UpdateRects: walks 'this->hidden->buffer' (the
     screen surface pixels), converts each pixel to RGB565, writes
     to the active DDR3 buffer, and flips the control word
"""

import sys

INJECT_INCLUDES = """
/* MiSTer DDR3 native-video bridge -- see patch_sdl_dummy.py */
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <stdint.h>
#include <pthread.h>

#define MISTER_DDR_PHYS_BASE   0x3A000000u
#define MISTER_DDR_REGION_SIZE 0x00100000u
#define MISTER_CTRL_OFFSET     0x00000000u
#define MISTER_BUF0_OFFSET     0x00000040u
#define MISTER_BUF1_OFFSET     0x00040040u
#define MISTER_FRAME_W         320
#define MISTER_FRAME_H         224  /* Sega CD V28 NTSC */
#define MISTER_FRAME_BYTES     (MISTER_FRAME_W * MISTER_FRAME_H * 2)

static int                 mister_fd        = -1;
static volatile uint8_t   *mister_ddr       = NULL;
static volatile uint32_t  *mister_ctrl      = NULL;
static uint32_t            mister_frame_cnt = 0;
static int                 mister_active_buf = 0;
static int                 mister_logged    = 0;
static pthread_t           mister_keepalive_tid;
static volatile int        mister_keepalive_run = 0;

/* Keepalive thread -- pings the FPGA frame counter every ~150ms even
 * when ARM isn't producing frames. The FPGA video reader
 * (openbor_video_reader.sv) has a staleness timeout: if frame_cnt
 * doesn't change for ~30 vblanks (~500ms) it sets frame_ready_reg=0
 * and BLANKS the screen. During heavy model loading on big PAKs
 * (He-Man, Avengers, late-build sets) individual model parses take
 * >500ms while the engine throttles update_loading calls -- so the
 * FPGA blanks then unblanks, producing the visible black/content
 * flicker on the loading screen.
 *
 * Bumping the counter without rewriting the buffer keeps the same
 * image on screen (FPGA re-reads the same active_buffer offset) but
 * keeps frame_ready_reg latched true. Same image, no flicker.
 *
 * IMPORTANT: mister_present writes buf X then TOGGLES mister_active_buf
 * to !X. So after a present, the LAST WRITTEN buffer is (!mister_active_buf).
 * Use that for the keepalive ctrl word -- otherwise the FPGA flips to
 * the OTHER buffer (which holds the previous frame) and the loading
 * bar jitters between two positions. Ported from MiSTer_OpenBOR_7533
 * 2026-05-13 (architectural-contract closure per CLAUDE.md). */
static void *mister_keepalive_fn(void *arg) {
    (void)arg;
    while (mister_keepalive_run) {
        usleep(150000); /* 150ms */
        if (mister_ctrl) {
            int last_written = !mister_active_buf & 1;
            mister_frame_cnt++;
            *mister_ctrl = (mister_frame_cnt << 2) | last_written;
        }
    }
    return NULL;
}

static void mister_ddr_init(void) {
    if (mister_ddr) return;
    mister_fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (mister_fd < 0) {
        fprintf(stderr, "MiSTer SDL: open /dev/mem failed\\n");
        return;
    }
    mister_ddr = (volatile uint8_t *)mmap(NULL, MISTER_DDR_REGION_SIZE,
        PROT_READ | PROT_WRITE, MAP_SHARED, mister_fd, MISTER_DDR_PHYS_BASE);
    if (mister_ddr == MAP_FAILED) {
        fprintf(stderr, "MiSTer SDL: mmap DDR3 failed\\n");
        mister_ddr = NULL;
        close(mister_fd);
        mister_fd = -1;
        return;
    }
    mister_ctrl = (volatile uint32_t *)(mister_ddr + MISTER_CTRL_OFFSET);
    *mister_ctrl = 0;
    fprintf(stderr, "MiSTer SDL: DDR3 mapped @ 0x%08X (driver=dummy_native)\\n",
            MISTER_DDR_PHYS_BASE);
    mister_keepalive_run = 1;
    pthread_create(&mister_keepalive_tid, NULL, mister_keepalive_fn, NULL);
}

static void mister_present(SDL_Surface *screen) {
    if (!mister_ddr || !screen || !screen->pixels) return;
    int w = screen->w, h = screen->h;
    int bpp = screen->format->BitsPerPixel;
    int pitch = screen->pitch;
    int Rshift = screen->format->Rshift;
    int Gshift = screen->format->Gshift;
    int Bshift = screen->format->Bshift;
    int Rloss  = screen->format->Rloss;
    int Gloss  = screen->format->Gloss;
    int Bloss  = screen->format->Bloss;
    SDL_Palette *pal = screen->format->palette;

    /* Anisotropic squish: fill entire 320x224 dest, X and Y scaled
     * independently. PAK content authored at non-224 native heights
     * (320x240 4086-era ~7% Y compress, 480x272 X+Y compress, 960x480
     * huge downscale) maps to fill the Sega CD V28 NTSC active area
     * exactly. Aspect distortion is intentional — matches Sega CD
     * displayed area edge-to-edge, no letterbox. Mirror of 7533. */
    int sx256 = (w * 256) / MISTER_FRAME_W;
    int sy256 = (h * 256) / MISTER_FRAME_H;
    int out_w = MISTER_FRAME_W;
    int out_h = MISTER_FRAME_H;
    int dst_y0 = 0;

    if (!mister_logged) {
        fprintf(stderr, "MiSTer SDL: first present %dx%d bpp=%d pitch=%d "
                "sx256=%d sy256=%d -> %dx%d "
                "Rmask=0x%08X Gmask=0x%08X Bmask=0x%08X palette=%p\\n",
                w, h, bpp, pitch, sx256, sy256, out_w, out_h,
                screen->format->Rmask, screen->format->Gmask,
                screen->format->Bmask, pal);
        mister_logged = 1;
    }

    uint32_t buf_off = mister_active_buf ? MISTER_BUF1_OFFSET : MISTER_BUF0_OFFSET;
    volatile uint16_t *dst = (volatile uint16_t *)(mister_ddr + buf_off);
    const uint8_t *rows = (const uint8_t *)screen->pixels;

    /* Clear BOTH buffers once on first frame for letterboxing.
     * Never clear per-frame — FPGA reads the zeroed buffer mid-write = flicker.
     * Black bars persist since nothing overwrites them. */
    {
        static int cleared = 0;
        if (!cleared) {
            volatile uint16_t *buf0 = (volatile uint16_t *)(mister_ddr + MISTER_BUF0_OFFSET);
            volatile uint16_t *buf1 = (volatile uint16_t *)(mister_ddr + MISTER_BUF1_OFFSET);
            memset((void*)buf0, 0, MISTER_FRAME_W * MISTER_FRAME_H * 2);
            memset((void*)buf1, 0, MISTER_FRAME_W * MISTER_FRAME_H * 2);
            cleared = 1;
        }
    }

    if (bpp == 32) {
        for (int y = 0; y < out_h; y++) {
            int src_y = (y * sy256) / 256;
            const uint32_t *row = (const uint32_t *)(rows + src_y * pitch);
            volatile uint16_t *out_row = dst + (dst_y0 + y) * MISTER_FRAME_W;
            for (int x = 0; x < out_w; x++) {
                int src_x = (x * sx256) / 256;
                uint32_t px = row[src_x];
                uint8_t r = ((px & screen->format->Rmask) >> Rshift) << Rloss;
                uint8_t g = ((px & screen->format->Gmask) >> Gshift) << Gloss;
                uint8_t b = ((px & screen->format->Bmask) >> Bshift) << Bloss;
                out_row[x] = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
            }
        }
    }
    else if (bpp == 16) {
        for (int y = 0; y < out_h; y++) {
            int src_y = (y * sy256) / 256;
            const uint16_t *row = (const uint16_t *)(rows + src_y * pitch);
            volatile uint16_t *out_row = dst + (dst_y0 + y) * MISTER_FRAME_W;
            for (int x = 0; x < out_w; x++) {
                int src_x = (x * sx256) / 256;
                uint16_t px = row[src_x];
                uint8_t r = ((px & screen->format->Rmask) >> Rshift) << Rloss;
                uint8_t g = ((px & screen->format->Gmask) >> Gshift) << Gloss;
                uint8_t b = ((px & screen->format->Bmask) >> Bshift) << Bloss;
                out_row[x] = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
            }
        }
    }
    else if (bpp == 8 && pal) {
        for (int y = 0; y < out_h; y++) {
            int src_y = (y * sy256) / 256;
            const uint8_t *row = rows + src_y * pitch;
            volatile uint16_t *out_row = dst + (dst_y0 + y) * MISTER_FRAME_W;
            for (int x = 0; x < out_w; x++) {
                int src_x = (x * sx256) / 256;
                SDL_Color c = pal->colors[row[src_x]];
                out_row[x] = ((c.r >> 3) << 11) | ((c.g >> 2) << 5) | (c.b >> 3);
            }
        }
    }
    else {
        return;
    }

    mister_frame_cnt++;
    *mister_ctrl = (mister_frame_cnt << 2) | (mister_active_buf & 1);
    mister_active_buf ^= 1;
}
/* end MiSTer DDR3 bridge */
"""

def main():
    if len(sys.argv) != 2:
        print("usage: patch_sdl_dummy.py <SDL_nullvideo.c>", file=sys.stderr)
        sys.exit(1)
    path = sys.argv[1]
    with open(path) as f:
        src = f.read()

    # 1) Inject our helper code right after the existing #include block.
    inject_after = '#include "../../events/SDL_events_c.h"\n'
    if inject_after not in src:
        # SDL include layout might differ; fall back to the first occurrence
        # of an obvious SDL include and bolt on right after.
        inject_after = '#include "SDL_video.h"\n'
    if inject_after not in src:
        print("ERROR: couldn't find an include anchor to inject helpers", file=sys.stderr)
        sys.exit(2)
    src = src.replace(inject_after, inject_after + INJECT_INCLUDES, 1)

    # 2) Init the DDR3 mapping in VideoInit. Keep 8bpp default —
    #    mister_present() handles 8/16/32bpp surfaces via palette/mask conversion.
    init_anchor = "/* We're done!"
    if init_anchor in src:
        src = src.replace(init_anchor, "mister_ddr_init();\n\t" + init_anchor, 1)
        print("  VideoInit: mister_ddr_init() injected (8bpp default kept).")
    else:
            src = src.replace(
                "static int DUMMY_VideoInit(_THIS, SDL_PixelFormat *vformat)\n{",
                "static int DUMMY_VideoInit(_THIS, SDL_PixelFormat *vformat)\n{\n\tmister_ddr_init();",
                1
            )
            print("  Fallback 2: mister_ddr_init() injected (NO 32bpp override).")

    # 3) Make UpdateRects actually push the screen surface to DDR3.
    update_old = "static void DUMMY_UpdateRects(_THIS, int numrects, SDL_Rect *rects)\n{\n\t/* do nothing. */\n}"
    update_new = (
        "static void DUMMY_UpdateRects(_THIS, int numrects, SDL_Rect *rects)\n"
        "{\n"
        "\t/* SDL_VideoSurface is a macro expanding to (current_video->screen). */\n"
        "\tmister_present(SDL_VideoSurface);\n"
        "}"
    )
    if update_old not in src:
        print("ERROR: couldn't locate DUMMY_UpdateRects original body", file=sys.stderr)
        sys.exit(3)
    src = src.replace(update_old, update_new)

    with open(path, 'w') as f:
        f.write(src)
    print(f"Patched {path}: DDR3 bridge installed in dummy video driver.")

if __name__ == '__main__':
    main()
