import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from forge_character_studio.blender_bridge.version_pin import (
    PINNED_BLENDER_VERSION,
    BlenderVersionError,
    check_blender_version,
    require_pinned_blender,
)

RUN_TARGET = "forge_character_studio.blender_bridge.version_pin.subprocess.run"


def _completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


class BlenderVersionPinTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.executable = Path(self._tmp.name) / "blender.exe"

    def test_require_pinned_blender_accepts_matching_version(self):
        stdout = f"Blender {PINNED_BLENDER_VERSION}\nbuild details\n"
        with mock.patch(RUN_TARGET, return_value=_completed(stdout)) as run:
            path = require_pinned_blender(self.executable)
        self.assertEqual(path, self.executable)
        run.assert_called_once_with(
            [str(self.executable), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_require_pinned_blender_refuses_mismatched_version(self):
        with mock.patch(RUN_TARGET, return_value=_completed("Blender 3.6.0\n")):
            with self.assertRaises(BlenderVersionError):
                require_pinned_blender(self.executable)

    def test_require_pinned_blender_refuses_version_prefix_match(self):
        # Exact equality only: a longer version that starts with the pin must not pass.
        stdout = f"Blender {PINNED_BLENDER_VERSION}.1\n"
        with mock.patch(RUN_TARGET, return_value=_completed(stdout)):
            with self.assertRaises(BlenderVersionError):
                require_pinned_blender(self.executable)

    def test_require_pinned_blender_refuses_missing_executable(self):
        with self.assertRaises(BlenderVersionError):
            require_pinned_blender(Path(self._tmp.name) / "does-not-exist")

    def test_require_pinned_blender_refuses_nonzero_return_code(self):
        with mock.patch(RUN_TARGET, return_value=_completed("", returncode=1)):
            with self.assertRaises(BlenderVersionError):
                require_pinned_blender(self.executable)

    def test_require_pinned_blender_refuses_unparseable_output(self):
        with mock.patch(RUN_TARGET, return_value=_completed("no version here\n")):
            with self.assertRaises(BlenderVersionError):
                require_pinned_blender(self.executable)

    def test_check_blender_version_returns_parsed_version(self):
        with mock.patch(RUN_TARGET, return_value=_completed("Blender 4.2.0 LTS\n")):
            self.assertEqual(check_blender_version(self.executable), "4.2.0")

    def test_require_pinned_blender_refuses_timeout(self):
        timeout = subprocess.TimeoutExpired(cmd="blender", timeout=30)
        with mock.patch(RUN_TARGET, side_effect=timeout):
            with self.assertRaises(BlenderVersionError):
                require_pinned_blender(self.executable)

    def test_blender_version_error_is_value_error(self):
        self.assertTrue(issubclass(BlenderVersionError, ValueError))


if __name__ == "__main__":
    unittest.main()
