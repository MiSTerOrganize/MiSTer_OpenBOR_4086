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

#define MISTER_DDR_PHYS_BASE   0x3A000000u
#define MISTER_DDR_REGION_SIZE 0x00100000u
#define MISTER_CTRL_OFFSET     0x00000000u
#define MISTER_BUF0_OFFSET     0x00000040u
#define MISTER_BUF1_OFFSET     0x00040040u
#define MISTER_FRAME_W         320
#define MISTER_FRAME_H         240
#define MISTER_FRAME_BYTES     (MISTER_FRAME_W * MISTER_FRAME_H * 2)

static int                 mister_fd        = -1;
static volatile uint8_t   *mister_ddr       = NULL;
static volatile uint32_t  *mister_ctrl      = NULL;
static uint32_t            mister_frame_cnt = 0;
static int                 mister_active_buf = 0;
static int                 mister_logged    = 0;
/* Every MISTER_SAMPLE_EVERY frames, dump a 4x4 grid of sample pixel
 * values so we can inspect actual colours after OpenBOR + SDL ran. */
#define MISTER_SAMPLE_EVERY 120   /* ~2 seconds at 60 fps */

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

    /* Scale factor: if source is larger than 320x240, downsample.
     * 640x480 -> 2x, 480x272 -> ~1.5x (round to 1), etc. */
    int sx = (w + MISTER_FRAME_W - 1) / MISTER_FRAME_W;  /* ceil(w/320) */
    int sy = (h + MISTER_FRAME_H - 1) / MISTER_FRAME_H;  /* ceil(h/240) */
    if (sx < 1) sx = 1;
    if (sy < 1) sy = 1;
    int out_w = w / sx;  /* output width after scaling */
    int out_h = h / sy;
    if (out_w > MISTER_FRAME_W) out_w = MISTER_FRAME_W;
    if (out_h > MISTER_FRAME_H) out_h = MISTER_FRAME_H;

    if (!mister_logged) {
        fprintf(stderr, "MiSTer SDL: first present %dx%d bpp=%d pitch=%d "
                "scale=%dx%d -> %dx%d "
                "Rmask=0x%08X Gmask=0x%08X Bmask=0x%08X palette=%p\\n",
                w, h, bpp, pitch, sx, sy, out_w, out_h,
                screen->format->Rmask, screen->format->Gmask,
                screen->format->Bmask, pal);
        mister_logged = 1;
    }

    uint32_t buf_off = mister_active_buf ? MISTER_BUF1_OFFSET : MISTER_BUF0_OFFSET;
    volatile uint16_t *dst = (volatile uint16_t *)(mister_ddr + buf_off);
    const uint8_t *rows = (const uint8_t *)screen->pixels;

    if (bpp == 32) {
        for (int y = 0; y < out_h; y++) {
            const uint32_t *row = (const uint32_t *)(rows + (y * sy) * pitch);
            volatile uint16_t *out = dst + y * MISTER_FRAME_W;
            for (int x = 0; x < out_w; x++) {
                uint32_t px = row[x * sx];
                uint8_t r = ((px & screen->format->Rmask) >> Rshift) << Rloss;
                uint8_t g = ((px & screen->format->Gmask) >> Gshift) << Gloss;
                uint8_t b = ((px & screen->format->Bmask) >> Bshift) << Bloss;
                out[x] = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
            }
        }
    }
    else if (bpp == 16) {
        for (int y = 0; y < out_h; y++) {
            const uint16_t *row = (const uint16_t *)(rows + (y * sy) * pitch);
            volatile uint16_t *out = dst + y * MISTER_FRAME_W;
            for (int x = 0; x < out_w; x++) {
                uint16_t px = row[x * sx];
                uint8_t r = ((px & screen->format->Rmask) >> Rshift) << Rloss;
                uint8_t g = ((px & screen->format->Gmask) >> Gshift) << Gloss;
                uint8_t b = ((px & screen->format->Bmask) >> Bshift) << Bloss;
                out[x] = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
            }
        }
    }
    else if (bpp == 8 && pal) {
        for (int y = 0; y < out_h; y++) {
            const uint8_t *row = rows + (y * sy) * pitch;
            volatile uint16_t *out = dst + y * MISTER_FRAME_W;
            for (int x = 0; x < out_w; x++) {
                SDL_Color c = pal->colors[row[x * sx]];
                out[x] = ((c.r >> 3) << 11) | ((c.g >> 2) << 5) | (c.b >> 3);
            }
        }
    }
    else {
        return;
    }

    /* Periodically dump a grid of sample pixels. Lets us see actual
     * colour values after OpenBOR + SDL ran, for comparing against
     * the expected on-screen colours. */
    if (bpp == 32 && (mister_frame_cnt % MISTER_SAMPLE_EVERY) == 0) {
        const uint32_t *rows = (const uint32_t *)screen->pixels;
        int pitch_w = pitch / 4;
        fprintf(stderr, "MiSTer SDL sample (frame %u):\\n", mister_frame_cnt);
        for (int gy = 0; gy < 3; gy++) {
            int sy = (h * (gy * 2 + 1)) / 6;
            for (int gx = 0; gx < 4; gx++) {
                int sx = (w * (gx * 2 + 1)) / 8;
                uint32_t px = rows[sy * pitch_w + sx];
                uint8_t r = ((px & screen->format->Rmask) >> Rshift) << Rloss;
                uint8_t g = ((px & screen->format->Gmask) >> Gshift) << Gloss;
                uint8_t b = ((px & screen->format->Bmask) >> Bshift) << Bloss;
                fprintf(stderr, "  (%3d,%3d) raw=0x%08X r=%02X g=%02X b=%02X\\n",
                        sx, sy, px, r, g, b);
            }
        }
        fflush(stderr);
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

    # 2) Init the DDR3 mapping in VideoInit.
    #    Keep default 8bpp — mister_present() handles 8/16/32bpp surfaces.
    #    DO NOT override to 32bpp: causes OpenBOR to allocate 4x larger
    #    internal buffers, exhausting RAM during model loading → segfault.
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

    # 3) DUMMY_SetVideoMode: log bpp but don't force it — mister_present handles all bpp.

    # 4) Make UpdateRects actually push the screen surface to DDR3.
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
