import ctypes.util
import importlib.metadata
import json
import os
import platform
import subprocess
import traceback
from pathlib import Path

report = {"node": platform.node(), "environment": {k: os.environ.get(k) for k in (
    "CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES", "SLURM_JOB_GPUS", "SLURM_STEP_GPUS",
    "PYTHONPATH", "LD_LIBRARY_PATH", "VLLM_PLATFORM", "VLLM_TARGET_DEVICE")}}

def check(name, fn):
    try:
        report[name] = {"ok": True, "value": fn()}
    except Exception as e:
        report[name] = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}

def torch_check():
    import torch
    out = {"version": torch.__version__, "path": torch.__file__, "cuda_build": torch.version.cuda,
           "available": torch.cuda.is_available(), "count": torch.cuda.device_count()}
    try:
        out["allocation"] = torch.ones(1, device="cuda").item()
        out["name"] = torch.cuda.get_device_name(0)
    except Exception as e:
        out["allocation_error"] = f"{type(e).__name__}: {e}"
    return out

def nvml_check():
    from vllm.utils.import_utils import import_pynvml
    p = import_pynvml()
    p.nvmlInit()
    try:
        return {"module": p.__file__, "driver": p.nvmlSystemGetDriverVersion(),
                "count": p.nvmlDeviceGetCount()}
    finally:
        p.nvmlShutdown()

def vllm_check():
    from vllm.platforms import current_platform
    return {"class": f"{type(current_platform).__module__}.{type(current_platform).__name__}",
            "device_type": current_platform.device_type}

check("packages", lambda: {k: importlib.metadata.version(k) for k in ("torch", "vllm", "nvidia-ml-py")})
check("nvidia_smi", lambda: subprocess.check_output(["nvidia-smi", "-L"], text=True, stderr=subprocess.STDOUT))
check("torch", torch_check)
check("nvml", nvml_check)
check("vllm", vllm_check)
check("loaded_driver_libraries", lambda: sorted({x.split()[-1] for x in Path("/proc/self/maps").read_text().splitlines()
      if "libcuda" in x or "libnvidia" in x}))
print(json.dumps(report, indent=2), flush=True)
if os.environ.get("GPU_PROBE_OUT"):
    Path(os.environ["GPU_PROBE_OUT"]).write_text(json.dumps(report, indent=2) + "\n")
