#!/bin/bash
# openbor_daemon.sh — Auto-start OpenBOR engine when core loads
#
# Uses mkdir as atomic lock to guarantee only ONE daemon runs.
# Uses wait to guarantee only ONE binary runs at a time.
# No race conditions — process must fully exit before next spawn.

LOCKDIR="/tmp/openbor_daemon.lock"
PIDFILE="/tmp/openbor_arm.pid"
GAMEDIR="/media/fat/games/OpenBOR"
BINARY="$GAMEDIR/OpenBOR"

# Prevent multiple daemon instances
if ! mkdir "$LOCKDIR" 2>/dev/null; then
    OLDPID=$(cat "$LOCKDIR/pid" 2>/dev/null)
    if [ -n "$OLDPID" ] && kill -0 "$OLDPID" 2>/dev/null; then
        exit 0
    fi
    rm -rf "$LOCKDIR"
    mkdir "$LOCKDIR" 2>/dev/null || exit 0
fi
echo $$ > "$LOCKDIR/pid"

CHILD=""
cleanup() {
    [ -n "$CHILD" ] && kill $CHILD 2>/dev/null
    rm -f "$PIDFILE"
    rm -rf "$LOCKDIR"
    exit 0
}
trap cleanup TERM INT

FIRST_LOAD=1
while true; do
    CUR=$(cat /tmp/CORENAME 2>/dev/null)

    if [ "$CUR" = "OpenBOR" ] && [ -z "$CHILD" ]; then
        # No binary running — start one
        if [ "$FIRST_LOAD" = "1" ]; then
            sleep 1  # FPGA settle on first load only
            FIRST_LOAD=0
        fi
        export SDL_VIDEODRIVER=dummy
        cd "$GAMEDIR"
        # Rotate the diagnostic log on every launch so we can inspect
        # what NativeVideoWriter / NativeAudioWriter reported and which
        # PAK path was chosen (stderr has "first frame %dx%d bpp=%d",
        # "MiSTer OSD: cached PAK", etc).
        mkdir -p Logs
        mv -f Logs/OpenBOR.log Logs/OpenBOR.prev.log 2>/dev/null
        ./OpenBOR > Logs/OpenBOR.log 2>&1 &
        CHILD=$!
        echo $CHILD > "$PIDFILE"
    fi

    if [ -n "$CHILD" ]; then
        if ! kill -0 $CHILD 2>/dev/null; then
            # Process exited (quit, reset pak, or crash) — reap it
            wait $CHILD 2>/dev/null
            CHILD=""
            rm -f "$PIDFILE"
            # Don't sleep — restart fast on next iteration
            continue
        fi
        if [ "$CUR" != "OpenBOR" ]; then
            # User left the core -- kill binary and clear cached state
            # so the next entry goes through MiSTer's OSD picker instead
            # of auto-loading the previous PAK.
            kill $CHILD 2>/dev/null
            wait $CHILD 2>/dev/null
            CHILD=""
            FIRST_LOAD=1
            rm -f "$PIDFILE"
            rm -f /tmp/openbor_current.pak
            # MiSTer tracks per-slot last-file state across several
            # extensions: .cfg (options), .f0 (last file slot 0), .s0
            # (last SD mount). Nuke the whole OpenBOR.* family so the
            # next entry re-opens the OSD picker.
            rm -f /media/fat/config/OpenBOR.cfg \
                  /media/fat/config/OpenBOR.f0 \
                  /media/fat/config/OpenBOR.f1 \
                  /media/fat/config/OpenBOR.s0
        fi
    fi

    sleep 1
done
