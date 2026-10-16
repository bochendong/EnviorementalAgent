"""Find a driver-library preload when the Python runtime cannot find NVML by soname.

Alliance's Python can use a different library search path from system tools such as nvidia-smi.
Print only the fallback library path, or nothing when normal loading works. The launcher passes it
to the server through LD_PRELOAD so spawned vLLM processes inherit the same fix.
"""

import ctypes
import os
import sys
from pathlib import Path

SONAME = "libnvidia-ml.so.1"
CANDIDATES = (
    "/usr/lib64/libnvidia-ml.so.1",
    "/usr/lib64/nvidia/libnvidia-ml.so.1",
    "/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1",
    "/usr/lib/nvidia/libnvidia-ml.so.1",
)


def find_preload(load=ctypes.CDLL, candidates=CANDIDATES):
    try:
        load(SONAME)
        return ""
    except OSError as original:
        errors = [str(original)]
    for name in candidates:
        path = Path(name)
        if not path.is_absolute() or not path.is_file():
            continue
        try:
            load(str(path))
            return str(path)
        except OSError as error:
            errors.append(f"{path}: {error}")
    raise RuntimeError("Cannot load NVIDIA NVML. " + "; ".join(errors))


if __name__ == "__main__":
    try:
        override = os.environ.get("NVML_LIBRARY_PATH")
        print(find_preload(candidates=(override,) if override else CANDIDATES))
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
