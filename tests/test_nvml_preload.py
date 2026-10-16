import tempfile
import unittest
from pathlib import Path

from slurm.nvml_preload import SONAME, find_preload


class NvmlPreloadTests(unittest.TestCase):
    def test_normal_loader_needs_no_preload(self):
        self.assertEqual(find_preload(load=lambda name: object(), candidates=()), "")

    def test_absolute_library_repairs_soname_lookup_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / SONAME
            library.touch()

            def load(name):
                if name == SONAME:
                    raise OSError("NVML not on the runtime search path")
                self.assertEqual(name, str(library))
                return object()

            self.assertEqual(find_preload(load=load, candidates=(str(library),)), str(library))

    def test_unloadable_library_reports_underlying_error(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Path(directory) / SONAME
            library.touch()

            def load(name):
                raise OSError("driver library dependency missing")

            with self.assertRaisesRegex(RuntimeError, "driver library dependency missing"):
                find_preload(load=load, candidates=(str(library),))

    def test_missing_library_is_not_returned(self):
        def load(name):
            raise OSError("no NVML")

        with self.assertRaisesRegex(RuntimeError, "Cannot load NVIDIA NVML"):
            find_preload(load=load, candidates=("/does-not-exist/libnvidia-ml.so.1",))
