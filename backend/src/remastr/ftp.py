"""FTP(S) file transfer with resume support, plus Plex <-> FTP path mapping."""

import ftplib
import posixpath
import ssl
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from remastr.config import PathMapping, Settings

TransferProgress = Callable[[int, int], None]
"""(bytes done, bytes total)"""

_BLOCK = 1024 * 1024


class TransferCancelled(Exception):
    pass


class PathMapper:
    def __init__(self, mappings: list[PathMapping]):
        # Longest prefix first so nested mappings win
        self._mappings = sorted(mappings, key=lambda m: len(m.plex), reverse=True)

    def to_ftp(self, plex_path: str) -> str:
        plex_path = plex_path.replace("\\", "/")  # Plex on Windows reports backslash paths
        for m in self._mappings:
            prefix = m.plex.replace("\\", "/").rstrip("/")
            if plex_path == prefix or plex_path.startswith(prefix + "/"):
                return m.ftp.rstrip("/") + plex_path[len(prefix) :]
        raise ValueError(f"No path mapping for Plex path {plex_path} (configure REMASTR_PATH_MAPPINGS)")


class FtpService:
    def __init__(self, settings: Settings):
        self._s = settings

    @contextmanager
    def connect(self) -> Iterator[ftplib.FTP]:
        if not self._s.ftp_host:
            raise RuntimeError("REMASTR_FTP_HOST is not configured")
        if self._s.ftp_tls:
            # ftplib does not verify certificates by default; always verify (optionally against a private CA)
            cafile = str(self._s.ca_bundle) if self._s.ca_bundle else None
            ftp: ftplib.FTP = ftplib.FTP_TLS(context=ssl.create_default_context(cafile=cafile))
        else:
            ftp = ftplib.FTP()
        ftp.encoding = "utf-8"
        ftp.connect(self._s.ftp_host, self._s.ftp_port, timeout=60)
        ftp.login(self._s.ftp_user, self._s.ftp_password)
        if isinstance(ftp, ftplib.FTP_TLS):
            ftp.prot_p()
        ftp.set_pasv(True)
        ftp.voidcmd("TYPE I")
        try:
            yield ftp
        finally:
            try:
                ftp.quit()
            except (ftplib.Error, OSError):
                ftp.close()

    @staticmethod
    def _size(ftp: ftplib.FTP, path: str) -> int | None:
        try:
            ftp.voidcmd("TYPE I")  # listings switch ftplib to ASCII mode, where SIZE is refused
            return ftp.size(path)
        except ftplib.error_perm:
            return None

    def size(self, remote: str) -> int | None:
        with self.connect() as ftp:
            return self._size(ftp, remote)

    def download(
        self,
        remote: str,
        local: Path,
        on_progress: TransferProgress | None = None,
        cancel: threading.Event | None = None,
    ) -> None:
        """Download to local, resuming a previous partial download (local + '.part')."""
        part = local.with_name(local.name + ".part")
        local.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as ftp:
            total = self._size(ftp, remote) or 0
            offset = part.stat().st_size if part.exists() else 0
            if total and offset > total:
                part.unlink()
                offset = 0
            done = offset
            with open(part, "ab") as f:

                def block(data: bytes) -> None:
                    nonlocal done
                    if cancel is not None and cancel.is_set():
                        raise TransferCancelled()
                    f.write(data)
                    done += len(data)
                    if on_progress:
                        on_progress(done, total)

                if not total or offset < total:
                    ftp.retrbinary(f"RETR {remote}", block, blocksize=_BLOCK, rest=offset or None)
        if total and part.stat().st_size != total:
            raise OSError(f"Download incomplete: {part.stat().st_size} of {total} bytes")
        part.replace(local)

    def upload(
        self,
        local: Path,
        remote: str,
        on_progress: TransferProgress | None = None,
        cancel: threading.Event | None = None,
    ) -> None:
        """Upload, resuming if the remote file is shorter than the local one. Verifies the final size.

        Resuming assumes the remote prefix belongs to the same local file: callers must use a remote name that is
        unique per local file (see service.upload_tmp_name)."""
        total = local.stat().st_size
        with self.connect() as ftp:
            self._makedirs(ftp, posixpath.dirname(remote))
            offset = self._size(ftp, remote) or 0
            if offset > total:
                ftp.delete(remote)
                offset = 0
            done = offset

            def block(data: bytes) -> None:
                nonlocal done
                if cancel is not None and cancel.is_set():
                    raise TransferCancelled()
                done += len(data)
                if on_progress:
                    on_progress(done, total)

            if offset < total:
                with open(local, "rb") as f:
                    f.seek(offset)
                    ftp.storbinary(f"STOR {remote}", f, blocksize=_BLOCK, callback=block, rest=offset or None)
            remote_size = self._size(ftp, remote)
        if remote_size != total:
            raise OSError(f"Upload verification failed: remote {remote_size} vs local {total} bytes")

    def rename(self, src: str, dst: str) -> None:
        with self.connect() as ftp:
            self._makedirs(ftp, posixpath.dirname(dst))
            ftp.rename(src, dst)

    def exists(self, remote: str) -> bool:
        return self.size(remote) is not None

    @staticmethod
    def _makedirs(ftp: ftplib.FTP, path: str) -> None:
        current = ""
        for part in [p for p in path.split("/") if p]:
            current += "/" + part
            try:
                ftp.mkd(current)
            except ftplib.error_perm:
                pass  # exists (or no permission; the following STOR will tell)
