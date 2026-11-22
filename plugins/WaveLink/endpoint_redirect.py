import ctypes
import logging
import queue
import threading
from collections.abc import Callable

from volume_osd import VolumeOsdHider

logger = logging.getLogger(__name__)


def list_active_playback_devices() -> list[tuple[str, str]]:
    from pycaw.constants import DEVICE_STATE, EDataFlow
    from pycaw.utils import AudioUtilities

    devices = AudioUtilities.GetAllDevices(
        data_flow=EDataFlow.eRender.value,
        device_state=DEVICE_STATE.ACTIVE.value,
    )
    return [
        (str(device.id), str(device.FriendlyName or device.id))
        for device in devices
        if device.id
    ]


class EndpointVolumeRedirector:
    def __init__(
        self,
        endpoint_id: str,
        on_change: Callable[[bool], None],
    ) -> None:
        self.endpoint_id = endpoint_id
        self.on_change = on_change
        self._events: queue.Queue[float | None] = queue.Queue()
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._startup_error: Exception | None = None
        self._endpoint = None
        self._callback = None
        self._osd_hider = VolumeOsdHider()
        self._osd_hider_active = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        try:
            self._osd_hider.start()
            self._osd_hider_active = True
        except Exception:
            self._osd_hider_active = False
            logger.exception(
                "Could not start Volume OSD hiding; endpoint redirection will continue"
            )
        self._ready.clear()
        self._stop.clear()
        self._startup_error = None
        self._thread = threading.Thread(
            target=self._run,
            name="WaveLinkEndpointRedirect",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=5):
            self.stop()
            raise TimeoutError("Timed out while starting the audio endpoint listener")
        if self._startup_error is not None:
            raise RuntimeError(
                f"Could not monitor audio endpoint {self.endpoint_id}"
            ) from self._startup_error

    def stop(self) -> None:
        self._stop.set()
        self._events.put(None)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
            if self._thread.is_alive():
                logger.error("Audio endpoint listener did not stop in time")
        self._thread = None
        if self._osd_hider_active:
            self._osd_hider.stop()
            self._osd_hider_active = False

    def _run(self) -> None:
        comtypes = None
        initialized = False
        registered = False
        try:
            import comtypes as comtypes_module
            from comtypes import GUID
            from pycaw.callbacks import AudioEndpointVolumeCallback
            from pycaw.constants import DEVICE_STATE, EDataFlow
            from pycaw.utils import AudioUtilities

            comtypes = comtypes_module
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            initialized = True
            devices = AudioUtilities.GetAllDevices(
                data_flow=EDataFlow.eRender.value,
                device_state=DEVICE_STATE.ACTIVE.value,
            )
            device = next(
                (
                    candidate
                    for candidate in devices
                    if str(candidate.id) == self.endpoint_id
                ),
                None,
            )
            if device is None:
                raise RuntimeError(
                    f"Audio endpoint {self.endpoint_id} is not available"
                )

            endpoint = device.EndpointVolume
            initial_volume = float(endpoint.GetMasterVolumeLevelScalar())
            event_context = GUID("{6A9E9FC5-E157-4F47-BB1D-4F9A2C0D4E31}")

            class VolumeCallback(AudioEndpointVolumeCallback):
                def on_notify(
                    callback_self,
                    new_volume,
                    new_mute,
                    context,
                    channels,
                    channel_volumes,
                ):
                    if (
                        context
                        and str(context.contents).casefold()
                        == str(event_context).casefold()
                    ):
                        return
                    if abs(float(new_volume) - initial_volume) < 0.0001:
                        return
                    self._events.put(float(new_volume))

            callback = VolumeCallback()
            endpoint.RegisterControlChangeNotify(callback)
            registered = True
            self._endpoint = endpoint
            self._callback = callback
            self._ready.set()

            while not self._stop.is_set():
                try:
                    changed_volume = self._events.get(timeout=0.1)
                except queue.Empty:
                    continue
                if changed_volume is None:
                    break

                if abs(changed_volume - initial_volume) < 0.0001:
                    continue
                endpoint.SetMasterVolumeLevelScalar(
                    initial_volume,
                    ctypes.byref(event_context),
                )
                self.on_change(changed_volume > initial_volume)
        except Exception as exc:
            if not self._ready.is_set():
                self._startup_error = exc
                self._ready.set()
            else:
                logger.exception("Audio endpoint volume redirection failed")
        finally:
            if registered:
                try:
                    self._endpoint.UnregisterControlChangeNotify(self._callback)
                except Exception:
                    logger.exception("Could not unregister audio endpoint callback")
            self._callback = None
            self._endpoint = None
            if initialized and comtypes is not None:
                comtypes.CoUninitialize()
