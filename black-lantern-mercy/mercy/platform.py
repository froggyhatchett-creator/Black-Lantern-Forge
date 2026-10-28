"""Host services: replace this adapter when integrating another OS."""
import os
import platform
from pathlib import Path
from datetime import datetime


class HostPlatform:
    def data_dir(self):
        if os.name == "nt":
            return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "BlackLantern/Mercy-v02"
        return Path.home() / ".local/share/black-lantern-mercy-v02"

    def current_time(self):
        return {"time": datetime.now().astimezone().isoformat()}

    def system_info(self):
        return {"os": platform.system(), "architecture": platform.machine()}


class ProfileLock:
    """OS releases ownership after process exit; the small lock file may remain."""
    def __init__(self, path):
        self.stream = path.open('a+b')
        try:
            self.stream.seek(0, 2)
            if self.stream.tell() == 0:
                self.stream.write(b'0')
                self.stream.flush()
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            raise RuntimeError('Profile is already open in another Mercy instance.') from exc

    def close(self):
        if self.stream.closed:
            return
        self.stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.stream, fcntl.LOCK_UN)
        self.stream.close()
