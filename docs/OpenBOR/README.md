# MiSTer_OpenBOR

Hybrid ARM+FPGA OpenBOR core for MiSTer FPGA with native video output. Inspired by the work of [SumolX](https://github.com/SumolX), who created the [first OpenBOR port for MiSTer](https://github.com/SumolX/MiSTer_OpenBOR).

## Features

- **Native FPGA video output** — 320×240 @ ~59.45Hz through MiSTer's native video pipeline
- **CRT support** — scanlines, shadow masks, and analog video output for CRT displays
- **MiSTer OSD integration** — load PAK files from the file browser
- **Hot-swap PAKs** — load a new PAK from the OSD while a game is playing
- **4-player support** — connect up to 4 controllers, add players by pressing START
- **Controller support** — d-pad, analog stick, and button mapping through MiSTer's input system
- **Custom pause menu** — Continue / Options / Reset Pak / Quit
- **Auto-launch** — OpenBOR starts automatically when the core is loaded

## Quick Install

1. Copy `Scripts/Install_OpenBOR.sh` to `/media/fat/Scripts/` on your MiSTer SD card
2. From the MiSTer main menu, go to Scripts and run **Install_OpenBOR**
3. Done — load **OpenBOR** from the console menu to play

The install script downloads and installs everything: the FPGA core, ARM binary, and controller mapping.

## Manual Install

Extract the release zip to the root of your MiSTer SD card (`/media/fat/`). The folder structure mirrors the SD card layout:

```
/media/fat/
├── _Console/
│   └── OpenBOR_YYYYMMDD.rbf               FPGA core (dated build)
├── config/
│   └── inputs/
│       └── OpenBOR_input_045e_0b12_v3.map  Controller map (generated from OSD)
├── docs/
│   └── OpenBOR/
│       └── README.md                       Documentation
├── games/
│   └── OpenBOR/
│       ├── OpenBOR                         ARM binary (engine)
│       ├── openbor_daemon.sh               Auto-launch daemon
│       └── Paks/                           Place your .pak game modules here
├── saves/
│   └── OpenBOR/                            Game saves (created automatically)
└── Scripts/
    └── Install_OpenBOR.sh                  Install script
```

## Game Modules (PAK Files)

Place your OpenBOR PAK files in `/media/fat/games/OpenBOR/Paks/`.

Build 3979 runs the vast majority of OpenBOR mods, including Streets of Rage Remake, Final Fight LNS, Golden Axe Remake, Turtles Ninjas and Battletoads, Simpsons Treehouse of Horror, and most of the LaunchBox OpenBOR collection.

## Controls

| Button          | Action                  |
|-----------------|-------------------------|
| A               | Attack / confirm        |
| B               | Jump                    |
| X               | Special / back          |
| Y               | Attack2                 |
| D-pad / Analog  | Move                    |
| Start           | Pause / add player      |
| Menu button     | MiSTer OSD menu         |

All 4 players use the same button layout. Remap buttons from the MiSTer OSD (press F12 on keyboard, or the OSD button on your IO board).

## Pause Menu

Press START during gameplay:

- **Continue** — resume gameplay
- **Options** — adjust Music Volume and SFX Volume with D-pad left/right, select Back to return
- **Reset Pak** — restart the current PAK fresh
- **Quit** — exit to PAK browser

Navigate with D-pad up/down. Press Attack to choose, Special to go back.

## FPGA Technical Details

- Resolution: 320×240 active, 500×263 total
- Refresh: 7,812,500 / (500×263) = ~59.45 Hz
- H-sync: 7,812,500 / 500 = 15,625 Hz (NTSC-compatible)
- Pixel clock: 31.25 MHz CLK_VIDEO / 4 = 7.8125 MHz effective
- Pixel format: RGB565 (16 bits per pixel)
- Frame size: 320 × 240 × 2 = 153,600 bytes
- DDR3 bandwidth: 153,600 × 60 = ~9.2 MB/s
- Double-buffered via DDR3 with ARM writing one buffer while FPGA reads the other

## OpenBOR Build Info

This core runs OpenBOR Build 3979, cross-compiled for MiSTer's ARM Cortex-A9 from the [rofl0r/openbor](https://github.com/rofl0r/openbor) SVN branch (commit 3b0a718). Built with arm-linux-gnueabihf-gcc 13.3.0, SDL 1.2.15, libvorbis/libogg statically linked.

## Credits

- **SumolX** — Created the [first OpenBOR port for MiSTer](https://github.com/SumolX/MiSTer_OpenBOR)
- **OpenBOR Team** — Senile Team, ChronoCrash community, DCurrent, Plombo, Utunnels, White Dragon. Visit [chronocrash.com](https://www.chronocrash.com)
- **Sorgelig & MiSTer Community** — MiSTer FPGA framework

## License

GPL-3.0. See LICENSE. OpenBOR itself is BSD-3-Clause.
