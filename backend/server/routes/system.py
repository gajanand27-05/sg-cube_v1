import logging

import psutil
from fastapi import APIRouter

log = logging.getLogger(__name__)
router = APIRouter(prefix="/system", tags=["system"])


@router.get("/stats")
def system_stats():
    try:
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        net = psutil.net_io_counters()

        return {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": mem.percent,
            "memory_used_gb": round(mem.used / (1024 ** 3), 1),
            "memory_total_gb": round(mem.total / (1024 ** 3), 1),
            "disk_percent": disk.percent,
            "disk_used_gb": round(disk.used / (1024 ** 3), 1),
            "disk_total_gb": round(disk.total / (1024 ** 3), 1),
            "net_down_mb": 0,
            "net_up_mb": 0,
            "temp_c": None,
        }
    except Exception as e:
        log.warning(f"System stats failed: {e}")
        return {"error": str(e)}
