import json
import websocket

port = 28198
url = f"ws://127.0.0.1:{port}"
print(f"Connecting to dynamic port {url}...")

try:
    ws = websocket.create_connection(url, header=["Origin: streamdeck://"], timeout=3.0)
    print("SUCCESS CONNECTING TO DYNAMIC PORT!")
    
    methods = [
        "getApplicationInfo",
        "getAllChannelInfo",
        "getInputs",
        "getChannels",
        "setInputMixer"
    ]
    for idx, m in enumerate(methods, 1):
        req = {"jsonrpc": "2.0", "id": idx, "method": m}
        if m == "setInputMixer":
            req["params"] = {"identifier": "Wave Link Music", "mixer": "local", "value": 50}
        ws.send(json.dumps(req))
        try:
            res = ws.recv()
            print(f"[{m}] Response: {res[:200]}")
        except Exception as e:
            print(f"[{m}] Recv error: {e}")
    ws.close()
except Exception as e:
    print("Connection failed:", e)
