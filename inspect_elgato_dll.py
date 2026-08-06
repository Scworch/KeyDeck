import re

dll_path = r"c:\надо\python\KeyDeck\Streamer.bot-x64-1.0.4\Streamer.bot.Elgato.dll"

with open(dll_path, "rb") as f:
    content = f.read()

# Extract UTF-8 and UTF-16 ASCII printable strings
ascii_strings = [s.decode('ascii', errors='ignore') for s in re.findall(b'[\x20-\x7E]{4,}', content)]
utf16_strings = [s.decode('utf-16le', errors='ignore') for s in re.findall(b'(?:[\x20-\x7E]\x00){4,}', content)]

all_strings = set(ascii_strings + utf16_strings)

keywords = ["wavelink", "wave", "mixer", "channel", "volume", "jsonrpc", "1824", "1884", "ws://", "http://", "setinput", "setmixer", "setchannel", "setvolume"]

print(f"Total strings extracted: {len(all_strings)}")
print("--- Matches containing relevant keywords ---")
matches = []
for s in sorted(all_strings):
    lower = s.lower()
    if any(kw in lower for kw in keywords):
        matches.append(s)

for m in matches[:150]:
    print(m)

print(f"\nTotal matched strings: {len(matches)}")
