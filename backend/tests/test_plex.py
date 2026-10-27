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
    v = video(f"{FOLDER}/BTR S00E03 - 1080p Remastr.mkv", f"{FOLDER}/BTR S00E03.mp4")
    assert PlexService(settings)._to_item(v).file == f"{FOLDER}/BTR S00E03.mp4"


def test_title_containing_remastr_is_not_mistaken_for_a_version(settings):
    v = video(f"{FOLDER}/Remastr - Remastr Story.mkv")
    assert PlexService(settings)._to_item(v).file.endswith("Remastr Story.mkv")


def test_only_remastr_versions_is_an_error(settings):
    with pytest.raises(ValueError, match="no original"):
        PlexService(settings)._to_item(video(f"{FOLDER}/BTR S00E03 - Remastr 720p.mkv"))


def test_all_originals_are_listed_as_versions(settings):
    v = video(f"{FOLDER}/BTR S00E03 - 1080p.mkv", f"{FOLDER}/BTR S00E03 - 1080p Remastr.mkv", f"{FOLDER}/BTR S00E03.ts")
    item = PlexService(settings)._to_item(v)
    assert [x.file for x in item.versions] == [f"{FOLDER}/BTR S00E03 - 1080p.mkv", f"{FOLDER}/BTR S00E03.ts"]
    assert item.file == item.versions[0].file and not item.version_pinned


def test_legacy_suffix_is_still_a_remastr_version(settings):
    v = video(f"{FOLDER}/Film - Remastr 1080p.mkv", f"{FOLDER}/Film - 1080p Remastr.mkv", f"{FOLDER}/Film.mp4")
    assert [x.file for x in PlexService(settings)._to_item(v).versions] == [f"{FOLDER}/Film.mp4"]


class FakeServer:
    def __init__(self, items):
        self.items = {str(i.ratingKey): i for i in items}
        self.queries = []
        self._session = SimpleNamespace(put="PUT")
        self.library = SimpleNamespace(sectionByID=lambda _: SimpleNamespace(recentlyAdded=self.recent))

    def fetchItem(self, key):
        return self.items[str(key)]

    def recent(self, maxresults, libtype):
        return list(self.items.values())

    def query(self, key, method):
        self.queries.append((key, method))


def plex_with(settings, *items):
    svc = PlexService(settings)
    svc._server = FakeServer(items)
    return svc


def movie(rating_key, *files):
    v = video(*files)
    v.ratingKey, v.type, v.librarySectionID = rating_key, "movie", 1
    return v


def test_separately_listed_upload_is_merged_into_original(settings):
    new = f"{FOLDER}/Lucky Fritz - 1080p Remastr.mkv"
    plex = plex_with(settings, movie(1322, f"{FOLDER}/Lucky Fritz.mp4"), movie(11780, new))
    assert plex.wait_and_group("1322", new, cancel=lambda: False) == "11780"
    assert plex.server.queries == [("/library/metadata/1322/merge?ids=11780", "PUT")]


def test_upload_already_grouped_is_left_alone(settings):
    new = f"{FOLDER}/Film - 1080p Remastr.mkv"
    plex = plex_with(settings, movie(1, f"{FOLDER}/Film.mp4", new))
    assert plex.wait_and_group("1", new, cancel=lambda: False) is None
    assert plex.server.queries == []


def test_waiting_for_scan_times_out(settings):
    plex = plex_with(settings, movie(1, f"{FOLDER}/Film.mp4"))
    with pytest.raises(TimeoutError):
        plex.wait_and_group("1", f"{FOLDER}/Film - 1080p Remastr.mkv", lambda: False, timeout_s=0, poll_s=0)
