import sys
import time
from pathlib import Path

# Add plugins/WaveLink to path
wavelink_dir = Path(__file__).resolve().parent / "plugins" / "WaveLink"
if str(wavelink_dir) not in sys.path:
    sys.path.insert(0, str(wavelink_dir))

import keyboard
from wavelink_api import (
    get_inputs,
    get_volume,
    set_volume,
    increase_volume,
    decrease_volume,
    mute,
    unmute,
    toggle_mute,
    WaveLinkError,
)

def main():
    print("=" * 50)
    print("Elgato Wave Link Standalone Controller")
    print("Binding F13 -> Increase Music Volume by 5%")
    print("Binding F14 -> Decrease Music Volume by 5%")
    print("Press Ctrl+C to exit.")
    print("=" * 50)

    CHANNEL = "Music"
    STEP = 5

    def on_f13():
        try:
            new_vol = increase_volume(CHANNEL, STEP)
            print(f"[+] F13 pressed -> {CHANNEL} volume: {new_vol}%")
        except WaveLinkError as e:
            print(f"[!] Error: {e}")

    def on_f14():
        try:
            new_vol = decrease_volume(CHANNEL, STEP)
            print(f"[-] F14 pressed -> {CHANNEL} volume: {new_vol}%")
        except WaveLinkError as e:
            print(f"[!] Error: {e}")

    keyboard.add_hotkey("f13", on_f13)
    keyboard.add_hotkey("f14", on_f14)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting Wave Link Controller...")

if __name__ == "__main__":
    main()
