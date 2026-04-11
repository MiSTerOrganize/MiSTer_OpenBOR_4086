/*
 * MiSTer_OpenBOR — Input Patch for sdl/control.c
 *
 * Bypasses SDL joystick input and reads directly from DDR3 where the
 * FPGA writes MiSTer controller state.
 *
 * PATCH: In sdl/control.c, replace the control_update() function.
 *
 * MiSTer joystick bitmask (from hps_io):
 *   bit 0  = Right       → FLAG_MOVERIGHT
 *   bit 1  = Left        → FLAG_MOVELEFT
 *   bit 2  = Down        → FLAG_MOVEDOWN
 *   bit 3  = Up          → FLAG_MOVEUP
 *   bit 4  = Button 0 (A)    → FLAG_ATTACK  (Attack/confirm)
 *   bit 5  = Button 1 (B)    → FLAG_JUMP    (Jump)
 *   bit 6  = Button 2 (X)    → FLAG_SPECIAL (Special)
 *   bit 7  = Button 3 (Y)    → FLAG_ATTACK2 (Attack2)
 *   bit 8  = Button 4 (Start) → FLAG_START
 *   bit 9  = Button 5 (Select) → exit(0) (Quit)
 *
 * Copyright (C) 2026 MiSTer Organize — GPL-3.0
 */

/* Replace the entire control_update() function with this: */

void control_update(s_playercontrols ** playercontrols, int numplayers)
{
    unsigned k;
    unsigned i;
    int player;
    int t;
    s_playercontrols * pcontrols;
    Uint8* keystate = (Uint8*)SDL_GetKeyState(NULL);

    getPads(keystate);
    for(player = 0; player < numplayers; player++)
    {
        pcontrols = playercontrols[player];
        k = 0;

#ifdef MISTER_NATIVE_VIDEO
        {
            uint32_t joy = NativeVideoWriter_ReadJoystick(player);

            /* Select button = immediate quit (daemon relaunches) */
            if (joy & 0x200) exit(0);

            /* Map MiSTer joystick bits to OpenBOR flags */
            if (joy & 0x001) k |= FLAG_MOVERIGHT;
            if (joy & 0x002) k |= FLAG_MOVELEFT;
            if (joy & 0x004) k |= FLAG_MOVEDOWN;
            if (joy & 0x008) k |= FLAG_MOVEUP;
            if (joy & 0x010) k |= FLAG_ATTACK;     /* A = Attack */
            if (joy & 0x020) k |= FLAG_JUMP;       /* B = Jump */
            if (joy & 0x040) k |= FLAG_SPECIAL;    /* X = Special */
            if (joy & 0x080) k |= FLAG_ATTACK2;    /* Y = Attack2 */
            if (joy & 0x100) k |= FLAG_START;      /* Start */
        }
#else
        /* Original SDL keyboard input */
        for(i = 0; i < 32; i++)
        {
            t = pcontrols->settings[i];
            if(t >= SDLK_FIRST && t < SDLK_LAST)
            {
                if(keystate[t]) k |= (1 << i);
            }
        }

        /* Original SDL joystick input */
        if(usejoy)
        {
            for(i = 0; i < 32; i++)
            {
                t = pcontrols->settings[i];
                if(t >= JOY_LIST_FIRST && t <= JOY_LIST_LAST)
                {
                    int portnum = (t - JOY_LIST_FIRST - 1) / JOY_MAX_INPUTS;
                    int shiftby = (t - JOY_LIST_FIRST - 1) % JOY_MAX_INPUTS;
                    if(portnum >= 0 && portnum <= 3)
                    {
                        if((joysticks[portnum].Data >> shiftby) & 1) k |= (1 << i);
                    }
                }
            }
        }
#endif
        pcontrols->kb_break = 0;
        pcontrols->newkeyflags = k & (~pcontrols->keyflags);
        pcontrols->keyflags = k;
    }
}
