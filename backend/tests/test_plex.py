from types import SimpleNamespace

import pytest

from remastr.plex import PlexService

FOLDER = "/data/tv/Big Time Rush/Specials"


def video(*files):
    media = [
        SimpleNamespace(
            parts=[SimpleNamespace(file=f, size=1)],
            width=640,
            height=360,
            duration=1000,
            container="mkv",
            videoCodec="h264",
            bitrate=1500,
        )
        for f in files
    ]
    return SimpleNamespace(
        ratingKey=1, title="t", type="episode", librarySectionTitle="TV", year=None, duration=1000, media=media
    )


def test_original_is_picked_even_if_plex_lists_the_remastr_version_first(settings):
    v = video(f"{FOLDER}/BTR S00E03 - Remastr 1080p.mkv", f"{FOLDER}/BTR S00E03.mp4")
    assert PlexService(settings)._to_item(v).file == f"{FOLDER}/BTR S00E03.mp4"


def test_title_containing_remastr_is_not_mistaken_for_a_version(settings):
    v = video(f"{FOLDER}/Remastr - Remastr Story.mkv")
    assert PlexService(settings)._to_item(v).file.endswith("Remastr Story.mkv")


def test_only_remastr_versions_is_an_error(settings):
    with pytest.raises(ValueError, match="no original"):
        PlexService(settings)._to_item(video(f"{FOLDER}/BTR S00E03 - Remastr 720p.mkv"))


def test_all_originals_are_listed_as_versions(settings):
    v = video(f"{FOLDER}/BTR S00E03 - 1080p.mkv", f"{FOLDER}/BTR S00E03 - Remastr 1080p.mkv", f"{FOLDER}/BTR S00E03.ts")
    item = PlexService(settings)._to_item(v)
    assert [x.file for x in item.versions] == [f"{FOLDER}/BTR S00E03 - 1080p.mkv", f"{FOLDER}/BTR S00E03.ts"]
    assert item.file == item.versions[0].file and not item.version_pinned
