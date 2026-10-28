import shutil
from pathlib import Path
from . import config
from .context import load_identity
from .platform import ProfileLock
from .storage import Store


class Profile:
    def __init__(self, path):
        path = Path(path).absolute()
        if path.is_symlink():
            raise ValueError('Profile cannot be a symbolic link.')
        path.mkdir(parents=True, exist_ok=True)
        self.path = path.resolve()
        for name in ('profile.lock', 'config.json', 'identity.json', 'mercy.sqlite3'):
            if (self.path / name).is_symlink():
                raise ValueError('Profile files cannot be symbolic links.')
        self.lock = ProfileLock(self.path / 'profile.lock')
        try:
            self.config = config.load(self.path / 'config.json')
            identity_path = self.path / 'identity.json'
            if not identity_path.exists():
                shutil.copyfile(Path(__file__).with_name('identity.json'), identity_path)
            if identity_path.stat().st_size > 16000:
                raise ValueError('Identity is too large.')
            self.identity = load_identity(identity_path)
            self.store = Store(self.path / 'mercy.sqlite3')
            if self.config['conversation_id'] not in {c['id'] for c in self.store.conversations()}:
                raise ValueError('Configured conversation does not exist.')
            self.recovered = self.store.recover()
        except BaseException:
            self.lock.close()
            raise

    def save_config(self, value):
        value = config.validate(value)
        if value['conversation_id'] not in {c['id'] for c in self.store.conversations()}:
            raise ValueError('Conversation does not exist.')
        config.save(self.path / 'config.json', value)
        self.config = value

    def close(self):
        self.lock.close()
