import os
import sys
import time
import clr

sb_dir = os.path.abspath(r"Streamer.bot-x64-1.0.4")
sys.path.append(sb_dir)

from System.Reflection import Assembly
import System
from System import Activator

def load_asm(filename):
    path = os.path.join(sb_dir, filename)
    bytes_data = System.IO.File.ReadAllBytes(path)
    return Assembly.Load(bytes_data)

load_asm("System.Threading.Tasks.Extensions.dll")
load_asm("System.Runtime.CompilerServices.Unsafe.dll")
load_asm("System.Text.Json.dll")
load_asm("Serilog.dll")
load_asm("websocket-sharp.dll")
load_asm("Newtonsoft.Json.dll")
load_asm("Streamer.bot.Common.dll")
elgato_asm = load_asm("Streamer.bot.Elgato.dll")

mixer_enum = elgato_asm.GetType("Streamer.bot.Elgato.WaveLink.Enums.MixerType")
local_mixer_val = System.Enum.Parse(mixer_enum, "Local")

client_type = elgato_asm.GetType("_9J8nHIpasSlsUaPNBCNB19VDI1i")
client = Activator.CreateInstance(client_type)

print("Connecting Streamer.bot WaveLinkClient...")
connect_method = client_type.GetMethod("_7nSAE3J7hkKq4QMRFGk8pipU3TN")
if connect_method:
    connect_task = connect_method.Invoke(client, None)
    print("Connect task triggered:", connect_task)

time.sleep(1.5)

print("\nSetting Local Mix Volume for 'Wave Link Music' to 30%...")
set_vol_method = client_type.GetMethod("_weACe7NGG4CKekW52V5lzi35LEB")
res_task = set_vol_method.Invoke(client, ["Wave Link Music", local_mixer_val, System.Int32(30), System.Boolean(False)])
print("Set volume task executed!")

time.sleep(1.0)
