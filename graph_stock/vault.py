"""Publish immutable generated notes without replacing any existing file."""

import hashlib
import os
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath


class NoteConflict(Exception):
    pass


def digest(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


class Vault:
    def __init__(self, root: Path):
        self.root = root.absolute()

    @contextmanager
    def parent(self, relative: str, create=False):
        parts = PurePosixPath(relative).parts
        if not parts or PurePosixPath(relative).is_absolute() or any(p in ("..", ".") for p in parts):
            raise ValueError("Invalid note path")
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                if create:
                    try:
                        os.mkdir(part, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            yield descriptor, parts[-1]
        finally:
            os.close(descriptor)

    @staticmethod
    def read_at(parent, name, binary=False):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, "rb") as handle:
            import stat
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise OSError("Note is not a regular file")
            limit = 25_000_000 if binary else 1_000_000
            data = handle.read(limit + 1)
            if len(data) > limit:
                raise OSError("Note exceeds size limit")
            return data if binary else data.decode("utf-8")

    def read(self, relative):
        with self.parent(relative) as (parent, name):
            return self.read_at(parent, name)

    def publish(self, relative: str, content: str):
        return self.publish_bytes(relative, content.encode())

    def publish_bytes(self, relative: str, content: bytes):
        with self.parent(relative, create=True) as (parent, name):
            temporary = f".graph-stock-{uuid.uuid4()}.tmp"
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=parent)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    # link is atomic and fails rather than replacing an existing note.
                    os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                except FileExistsError:
                    if self.read_at(parent, name, binary=True) != content:
                        raise NoteConflict("An existing note has different content") from None
                os.fsync(parent)
            finally:
                os.unlink(temporary, dir_fd=parent)
