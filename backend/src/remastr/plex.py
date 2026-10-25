"""Plex metadata access via python-plexapi."""

import re
import threading

import requests
from plexapi.media import Media
from plexapi.server import PlexServer
from plexapi.video import Episode, Movie, Video

from remastr.config import Settings
from remastr.models import Library, PlexItem


class PlexService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._server: PlexServer | None = None
        self._lock = threading.Lock()

    @property
    def server(self) -> PlexServer:
        with self._lock:
            if self._server is None:
                if not self._settings.plex_token:
                    raise RuntimeError("REMASTR_PLEX_TOKEN is not configured")
                session = requests.Session()
                if self._settings.ca_bundle:
                    session.verify = str(self._settings.ca_bundle)
                self._server = PlexServer(
                    self._settings.plex_url, self._settings.plex_token, session=session, timeout=30
                )
            return self._server

    def libraries(self) -> list[Library]:
        return [
            Library(key=str(s.key), title=s.title, type=s.type)
            for s in self.server.library.sections()
            if s.type in ("movie", "show")
        ]

    def search(self, query: str, library: str | None = None, limit: int = 50) -> list[PlexItem]:
        """Movies and episodes matching the query. For shows, matching show titles expand to their episodes."""
        sections = [s for s in self.server.library.sections() if s.type in ("movie", "show")]
        if library:
            sections = [s for s in sections if library in (str(s.key), s.title)]
        found: dict[str, Video] = {}
        for section in sections:
            if section.type == "movie":
                candidates = section.search(title=query, maxresults=limit)
            else:
                candidates = list(section.searchEpisodes(title=query, maxresults=limit))
                for show in section.search(title=query, maxresults=5):
                    candidates += show.episodes()
            for video in candidates:
                found.setdefault(str(video.ratingKey), video)
                if len(found) >= limit:
                    break
        return [self._to_item(v) for v in found.values() if v.media]

    def item(self, rating_key: str) -> PlexItem:
        video = self.server.fetchItem(int(rating_key))
        if not isinstance(video, (Movie, Episode)):
            raise ValueError(f"Item {rating_key} is not a movie or episode")
        return self._to_item(video)

    def refresh_folder(self, plex_path: str) -> None:
        """Partial library scan of the folder containing plex_path."""
        sep = "\\" if "\\" in plex_path else "/"
        folder = plex_path.rsplit(sep, 1)[0]
        for section in self.server.library.sections():
            if any(folder == loc.rstrip(sep) or folder.startswith(loc.rstrip(sep) + sep) for loc in section.locations):
                section.update(path=folder)
                return
        raise ValueError(f"No Plex library contains {folder}")

    def _original_media(self, video: Video) -> Media:
        """Plex groups remastr's "version" uploads (<name> - Remastr 1080p.mkv) with the original as versions of one
        item, in no guaranteed order. Downloads, output names and "replace" must always use the original."""
        suffix = re.escape(self._settings.version_suffix).replace(r"\{height\}", r"\d+")
        is_remastr = re.compile(suffix + r"\.[^./\\]+$")
        originals = [m for m in video.media if m.parts and not is_remastr.search(m.parts[0].file)]
        if not originals:
            raise ValueError(f"Item {video.ratingKey} only has remastr versions, no original file")
        return originals[0]

    def _to_item(self, video: Video) -> PlexItem:
        media = self._original_media(video)
        part = media.parts[0]
        is_episode = isinstance(video, Episode)
        return PlexItem(
            rating_key=str(video.ratingKey),
            title=video.title,
            type=video.type,
            library=video.librarySectionTitle,
            show=video.grandparentTitle if is_episode else None,
            season=video.parentIndex if is_episode else None,
            episode=video.index if is_episode else None,
            year=getattr(video, "year", None),
            file=part.file,
            size=part.size,
            width=media.width,
            height=media.height,
            duration_s=(media.duration or video.duration or 0) / 1000 or None,
            container=media.container,
            video_codec=media.videoCodec,
        )
