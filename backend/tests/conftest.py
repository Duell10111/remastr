from pathlib import Path

import pytest

from remastr.config import PathMapping, Settings
from remastr.models import PlexItem
from remastr.service import Remastr

ITEM = PlexItem(
    rating_key="42",
    title="Die geklauten Filme",
    type="episode",
    library="TV",
    show="Mickys Clubhaus",
    season=1,
    episode=1,
    file="/data/tv/Mickys Clubhaus/Season 01/Mickys Clubhaus - s01e01.ts",
    width=720,
    height=576,
    duration_s=1300,
)


class FakePlex:
    def __init__(self):
        self.refreshed: list[str] = []
        self.grouped: list[str] = []

    def libraries(self):
        return []

    def search(self, query, library=None, limit=50):
        return [ITEM]

    def item(self, rating_key):
        if rating_key != ITEM.rating_key:
            raise ValueError("unknown")
        return ITEM

    def refresh_folder(self, plex_path):
        self.refreshed.append(plex_path)

    def wait_and_group(self, rating_key, plex_path, cancel):
        self.grouped.append(plex_path)
        return None


class FakeFtp:
    def __init__(self):
        self.files: dict[str, bytes] = {"/tv/Mickys Clubhaus/Season 01/Mickys Clubhaus - s01e01.ts": b"original"}

    def download(self, remote, local: Path, on_progress=None, cancel=None):
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(self.files[remote])

    def upload(self, local: Path, remote, on_progress=None, cancel=None):
        self.files[remote] = local.read_bytes()

    def rename(self, src, dst):
        self.files[dst] = self.files.pop(src)

    def exists(self, remote):
        return remote in self.files


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        work_dir=tmp_path,
        plex_token="x",
        path_mappings=[PathMapping(plex="/data/tv", ftp="/tv")],
        ftp_archive_root="/archive",
    )


@pytest.fixture
def svc(settings) -> Remastr:
    return Remastr(settings, plex=FakePlex(), ftp=FakeFtp())
