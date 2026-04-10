# MiSTer_OpenBOR

Hybrid ARM+FPGA OpenBOR core for MiSTer FPGA with native video output. Based on the work of [SumolX](https://github.com/SumolX), who created the [original MiSTer OpenBOR port](https://github.com/SumolX/MiSTer_OpenBOR) and was the first person to bring OpenBOR to the MiSTer platform.

## Features

- 320×240 native FPGA video output with CRT scanline and shadow mask support
- OpenBOR Build 3979 — runs the vast majority of the OpenBOR mod catalog
- Load PAK files from the MiSTer OSD file browser
- 4-player support with per-player button remapping
- Custom pause menu: Continue / Options / Reset Pak / Quit

## Quick Install

1. Copy `Scripts/Install_OpenBOR.sh` to `/media/fat/Scripts/` on your MiSTer SD card
2. Run **Install_OpenBOR** from the Scripts menu
3. Load **OpenBOR** from the console menu

## PAK Files

Place your OpenBOR game modules in `/media/fat/games/OpenBOR/Paks/`

A large collection is available at the [OpenBOR-Packs archive](https://archive.org/details/OpenBOR-Paks).

## Controller Mapping

| Button   | Xbox Series X | Action                  |
|----------|---------------|-------------------------|
| A        | A             | Jump / confirm in menus |
| B        | B             | Punch                   |
| X        | X             | Special / back in menus |
| Y        | Y             | Block                   |
| Start    | Start         | Pause / add player      |
| Select   | Back          | Quit                    |

## SD Card Layout

```
/media/fat/
├── _Console/
│   └── OpenBOR_YYYYMMDD.rbf               FPGA core
├── config/
│   └── inputs/
│       └── OpenBOR_input_045e_0b12_v3.map  Controller map (generated from OSD)
├── docs/
│   └── OpenBOR/
│       └── README.md                       Full documentation
├── games/
│   └── OpenBOR/
│       ├── OpenBOR                         ARM binary
│       ├── openbor_daemon.sh               Auto-launch daemon
│       └── Paks/                           Place your .pak files here
├── saves/
│   └── OpenBOR/                            Game saves
└── Scripts/
    └── Install_OpenBOR.sh                  Install script
```

See [docs/OpenBOR/README.md](docs/OpenBOR/README.md) for full documentation, technical details, and build instructions.

## Credits

- **SumolX** — Original [MiSTer OpenBOR port](https://github.com/SumolX/MiSTer_OpenBOR)
- **OpenBOR Team** — [chronocrash.com](https://www.chronocrash.com)
- **MiSTer Organize** — FPGA hybrid core, Build 3979 upgrade, custom pause menu
- **Sorgelig & MiSTer Community** — MiSTer FPGA framework

## License

GPL-3.0. See LICENSE. OpenBOR itself is BSD-3-Clause.
