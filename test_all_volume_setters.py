import json
import time
import websocket

ws = websocket.create_connection("ws://127.0.0.1:1824", header=["Origin: streamdeck://"], timeout=3.0)
print("Connected to 1824!")

payloads = [
    ("setInputMixer", {"identifier": "Wave Link Music", "mixer": "local", "value": 50}),
    ("setInputMixer", {"identifier": "Wave Link Music", "value": 50}),
    ("setVolume", {"identifier": "Wave Link Music", "volume": 50}),
    ("setVolume", {"channel": "Wave Link Music", "volume": 50}),
    ("setLocalMixer", {"identifier": "Wave Link Music", "value": 50}),
    ("setChannel", {"identifier": "Wave Link Music", "localVolume": 50}),
    ("setChannel", {"id": "Wave Link Music", "volume": 50}),
    ("setMixer", {"identifier": "Wave Link Music", "volume": 50}),
    ("setLocalVolume", {"identifier": "Wave Link Music", "volume": 50}),
    ("setInputVolume", {"identifier": "Wave Link Music", "volume": 50}),
    ("setInputDevice", {"identifier": "Wave Link Music", "volume": 50}),
    ("setMix", {"identifier": "Wave Link Music", "volume": 50}),
]

for idx, (method, params) in enumerate(payloads, 1):
    req = {
        "jsonrpc": "2.0",
        "id": idx,
        "method": method,
        "params": params
    }
    ws.send(json.dumps(req))
    
    start = time.time()
    while time.time() - start < 1.0:
        try:
            raw = ws.recv()
            data = json.loads(raw)
            if data.get("id") == idx:
                print(f"Call {idx} [{method}]:", data)
                break
        except Exception:
            break

ws.close()
