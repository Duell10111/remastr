import pytest

from remastr.config import PathMapping
from remastr.ftp import PathMapper


def test_maps_longest_prefix():
    m = PathMapper([PathMapping(plex="/data", ftp="/all"), PathMapping(plex="/data/tv", ftp="/tv")])
    assert m.to_ftp("/data/tv/Show/S01/e1.ts") == "/tv/Show/S01/e1.ts"
    assert m.to_ftp("/data/movies/x.mkv") == "/all/movies/x.mkv"


def test_does_not_match_partial_folder_names():
    m = PathMapper([PathMapping(plex="/data/tv", ftp="/tv")])
    with pytest.raises(ValueError):
        m.to_ftp("/data/tvshows/x.ts")


def test_windows_plex_paths():
    m = PathMapper([PathMapping(plex="D:\\Media\\TV", ftp="/tv")])
    assert m.to_ftp("D:\\Media\\TV\\Show\\e1.ts") == "/tv/Show/e1.ts"
