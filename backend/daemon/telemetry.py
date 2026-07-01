import threading
import time
import logging
import psutil

from backend.core.events import get_bus, Priority
from backend.daemon.ui_events import SystemStatsEvent

log = logging.getLogger(__name__)

class TelemetryLoop:
    def __init__(self, interval: float = 2.0):
        self.interval = interval
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_net_io = None

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="telemetry-loop", daemon=True)
        self._thread.start()
        log.info("System telemetry loop started.")

    def stop(self):
        if self._thread:
            self._stop_event.set()
            self._thread.join(timeout=2.0)
            self._thread = None
            log.info("System telemetry loop stopped.")

    def _run(self):
        # Initialize net io counters
        self._last_net_io = psutil.net_io_counters()

        while not self._stop_event.is_set():
            try:
                # CPU
                cpu_percent = psutil.cpu_percent(interval=None)

                # Memory
                mem = psutil.virtual_memory()
                memory_percent = mem.percent
                memory_used_gb = mem.used / (1024 ** 3)
                memory_total_gb = mem.total / (1024 ** 3)

                # Disk
                disk = psutil.disk_usage('/')
                disk_percent = disk.percent
                disk_used_gb = disk.used / (1024 ** 3)
                disk_total_gb = disk.total / (1024 ** 3)

                # Network
                current_net_io = psutil.net_io_counters()
                if current_net_io and self._last_net_io:
                    bytes_recv = current_net_io.bytes_recv - self._last_net_io.bytes_recv
                    bytes_sent = current_net_io.bytes_sent - self._last_net_io.bytes_sent
                    net_down_bps = bytes_recv / self.interval
                    net_up_bps = bytes_sent / self.interval
                else:
                    net_down_bps = 0.0
                    net_up_bps = 0.0
                self._last_net_io = current_net_io

                # Temperature (fallback to None if unavailable on Windows)
                temp_c = None
                if hasattr(psutil, "sensors_temperatures"):
                    try:
                        temps = psutil.sensors_temperatures()
                        if temps:
                            # Grab the first available temperature sensor
                            for name, entries in temps.items():
                                if entries:
                                    temp_c = entries[0].current
                                    break
                    except Exception:
                        pass # Ignore permission errors

                event = SystemStatsEvent(
                    cpu_percent=round(cpu_percent, 1),
                    memory_percent=round(memory_percent, 1),
                    memory_used_gb=round(memory_used_gb, 2),
                    memory_total_gb=round(memory_total_gb, 2),
                    disk_percent=round(disk_percent, 1),
                    disk_used_gb=round(disk_used_gb, 1),
                    disk_total_gb=round(disk_total_gb, 1),
                    net_down_bps=round(net_down_bps, 2),
                    net_up_bps=round(net_up_bps, 2),
                    temp_c=round(temp_c, 1) if temp_c is not None else None
                )
                get_bus().publish(event, priority=Priority.LOW)

            except Exception as e:
                log.debug(f"Telemetry error: {e}")

            # Wait for interval or stop signal
            self._stop_event.wait(self.interval)

telemetry_loop = TelemetryLoop()
