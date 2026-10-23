"""Local working directory per Plex item:

<work_dir>/items/<rating_key>/
    item.json                 snapshot of the Plex metadata
    source/<original name>    downloaded original
    previews/<run id>/        preview clips (<preset>.mp4) + preview.json
    output/<name>.mkv         processed full-length files
"""

import re
from datetime import datetime
from pathlib import Path

from remastr.config import Settings
from remastr.models import LocalState, PlexItem, PreviewClip, PreviewRun


def plex_basename(plex_path: str) -> str:
    return re.split(r"[\\/]", plex_path)[-1]


class Workspace:
    def __init__(self, settings: Settings):
        self._s = settings
        self.root = settings.work_dir / "items"

    def item_dir(self, rating_key: str) -> Path:
        if not rating_key.isdigit():
            raise ValueError(f"Invalid rating key {rating_key!r}")
        return self.root / rating_key

    def save_item(self, item: PlexItem) -> None:
        d = self.item_dir(item.rating_key)
        d.mkdir(parents=True, exist_ok=True)
        (d / "item.json").write_text(item.model_dump_json(indent=2), "utf-8")

    def load_item(self, rating_key: str) -> PlexItem | None:
        p = self.item_dir(rating_key) / "item.json"
        return PlexItem.model_validate_json(p.read_text("utf-8")) if p.exists() else None

    def source_target(self, item: PlexItem) -> Path:
        return self.item_dir(item.rating_key) / "source" / plex_basename(item.file)

    def find_source(self, rating_key: str) -> Path | None:
        d = self.item_dir(rating_key) / "source"
        files = [p for p in d.glob("*") if p.is_file() and p.suffix != ".part"] if d.exists() else []
        return files[0] if files else None

    def new_preview_dir(self, rating_key: str) -> Path:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        d = self.item_dir(rating_key) / "previews" / run_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_preview(self, run_dir: Path, run: PreviewRun) -> None:
        (run_dir / "preview.json").write_text(run.model_dump_json(indent=2), "utf-8")

    def previews(self, rating_key: str) -> list[PreviewRun]:
        d = self.item_dir(rating_key) / "previews"
        runs = [PreviewRun.model_validate_json(p.read_text("utf-8")) for p in d.glob("*/preview.json")]
        return sorted(runs, key=lambda r: r.created_at, reverse=True)

    def preview_clip(self, run_dir: Path, preset_id: str, file: Path) -> PreviewClip:
        return PreviewClip(preset=preset_id, file=file.relative_to(run_dir.parent.parent).as_posix())

    def output_name(self, item: PlexItem, height: int) -> str:
        stem = Path(plex_basename(item.file)).stem
        return f"{stem}{self._s.version_suffix.format(height=height)}.mkv"

    def output_dir(self, rating_key: str) -> Path:
        return self.item_dir(rating_key) / "output"

    def outputs(self, rating_key: str) -> list[Path]:
        d = self.output_dir(rating_key)
        return (
            sorted(p for p in d.glob("*.mkv") if ".partial" not in p.name and ".video" not in p.name)
            if d.exists()
            else []
        )

    def local_state(self, rating_key: str) -> LocalState:
        base = self.item_dir(rating_key)
        src = self.find_source(rating_key)
        return LocalState(
            source=src.relative_to(base).as_posix() if src else None,
            previews=self.previews(rating_key),
            outputs=[p.relative_to(base).as_posix() for p in self.outputs(rating_key)],
        )

    def resolve(self, rating_key: str, rel_path: str) -> Path:
        """Resolve a workspace-relative path, refusing anything outside the item directory."""
        base = self.item_dir(rating_key).resolve()
        target = (base / rel_path).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise FileNotFoundError(rel_path)
        return target
