# OpenBOR_4086 diff / debug harness — AD-HOC ONLY (no mass-scan)

🛑 **4086 is the LEGACY-compat core. Do NOT mass-scan it against the PAK corpus.**
Per the corpus-class principle (`feedback_hybrid_core_diff_harness_required.md`):
a mass-scan is only meaningful against the PAK class the engine is *supposed* to
run. 4086 runs **legacy** PAKs; **modern PAKs crash it by design-incompatibility**
(they were never built for the 4086-era engine). A full-corpus crash scan on 4086
would be a flood of expected, never-fixable crashes that drown any real signal.

So 4086's harness is **ad-hoc only**: when debugging a *specific legacy PAK* that
4086 is meant to run (e.g. A Tale of Vengeance, Aliens Clash), run that one PAK
through the headless binary to reproduce/diagnose a crash or hang off-device —
never a corpus sweep. The **modern-corpus mass-scan lives on OpenBOR_7533** (the
modern engine that's supposed to run the modern corpus); see
`MiSTer_OpenBOR_7533/tools/harness/FINDINGS.md`.

## What's here
- `pak_decode_scan.py` — PAK-integrity (decode) scan; engine-agnostic, fine on any
  PAK set (validates packfile structure, not engine compatibility).
- `diff_harness.yml` + `build_headless.sh` — headless 4086 (SDL 1.2) build for
  **ad-hoc** legacy-PAK debugging. Crash (`SIGSEGV/ABRT` backtrace + addr2line) and
  hang (`--alarm`) tooling is the same model as 7533's.

## Status / remaining
The 4086 headless build is SDL **1.2** (vs 7533's SDL 2), so the
`apply_patches_headless` overrides (env-`OB_PAK` `main` + frame-counter/alarm hook)
need a 4086-specific video anchor — 4086's `video_copy_screen` is
`memcpy + SDL_Flip → DUMMY_UpdateRects`, not SDL2 `SDL_UpdateTexture`. Milestone 1a
(compile) is wired (`diff_harness.yml` + `build_headless.sh`); the 1b harness
overrides for ad-hoc run get finalized **when a 4086 legacy-PAK bug actually needs
off-device debugging** — no value finishing/iterating speculatively since 4086 is
not mass-scanned. Once finalized, ad-hoc use:
`OB_PAK=/paks/<legacy>.pak OB_FRAMES=N ./OpenBOR_headless` in an ubuntu glibc
container with SDL 1.2 runtime libs.
