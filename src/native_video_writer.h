#ifndef OPENBOR_NATIVE_VIDEO_WRITER_H
#define OPENBOR_NATIVE_VIDEO_WRITER_H

//
//  Native Video DDR3 Writer for OpenBOR on MiSTer
//
//  Maps /dev/mem at 0x3A000000 and writes 320x240 RGB565 frames
//  into a double-buffered DDR3 region. The FPGA-side openbor_video_reader
//  polls a control word and reads pixel data for native video output.
//
//  Usage:
//    NativeVideoWriter_Init();
//    // each frame:
//    NativeVideoWriter_WriteFrame(surface_pixels, 320, 240, bpp, palette);
//    // on shutdown:
//    NativeVideoWriter_Shutdown();
//
//  Copyright (C) 2026 MiSTer Organize — GPL-3.0
//

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/// Initialize the DDR3 direct writer. Maps /dev/mem at the native video
/// buffer region and clears both frame buffers. Returns true on success.
bool NativeVideoWriter_Init(void);

/// Release DDR3 mapping and close /dev/mem.
void NativeVideoWriter_Shutdown(void);

/// Write one 320x240 frame to DDR3 double-buffer, then flip the control word.
/// Handles 8bpp (paletted), 16bpp (RGB565), and 32bpp (RGBA) input.
/// @param pixels     Source pixel data from SDL surface (screen->pixels)
/// @param width      Surface width (typically 320)
/// @param height     Surface height (typically 240)
/// @param bpp        Bits per pixel (8, 16, or 32)
/// @param palette    SDL palette for 8bpp mode (NULL for 16/32bpp)
void NativeVideoWriter_WriteFrame(const void* pixels, int width, int height,
                                  int bpp, const void* palette);

/// True if the DDR3 writer has been initialized and is ready for frames.
bool NativeVideoWriter_IsActive(void);

/// Check if a new PAK has been loaded via OSD file browser.
/// Returns file size in bytes if a new PAK is available, 0 otherwise.
uint32_t NativeVideoWriter_CheckCart(void);

/// Read PAK data from DDR3 into the provided buffer.
/// @param buf       Destination buffer (must be at least max_size bytes)
/// @param max_size  Maximum bytes to read
/// @return Actual bytes read
uint32_t NativeVideoWriter_ReadCart(void* buf, uint32_t max_size);

/// Clear the cart control word so the FPGA knows the ARM has read the PAK.
void NativeVideoWriter_AckCart(void);

/// Read joystick state for a specific player from DDR3.
/// @param player  Player index (0-3)
/// @return MiSTer joystick bitmask: bit0=R, bit1=L, bit2=D, bit3=U,
///         bit4=btn0, bit5=btn1, ... (layout defined by CONF_STR J1 line)
uint32_t NativeVideoWriter_ReadJoystick(int player);

#ifdef __cplusplus
}
#endif

#endif
