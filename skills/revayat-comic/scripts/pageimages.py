"""File-backed eager image reads and counted loose-input admission."""
from __future__ import annotations

import os
from pathlib import Path

MAX_MEMBER_BYTES = 512 * 1024 ** 2
MAX_TOTAL_BYTES = 2 * 1024 ** 3
MAX_PAGE_PIXELS = 80_000_000


def load_image(path: str | os.PathLike[str]):
    import pageir as ir

    ir.require("PIL", "pillow", "reading comic pages")
    from PIL import Image

    # Decode eagerly while the file is open; RGB owns its pixels after close.
    with open(path, "rb") as stream:
        if os.fstat(stream.fileno()).st_size > MAX_MEMBER_BYTES:
            raise ValueError("image exceeds the encoded-byte limit")
        with Image.open(stream) as image:
            if image.width * image.height > MAX_PAGE_PIXELS:
                raise ValueError("image exceeds the decoded-pixel limit")
            return image.convert("RGB")


def copy_loose_images(sources, pages_dir: Path, *, member_limit: int,
                      total_limit: int) -> list[Path]:
    import pageir as ir

    sources = list(sources)
    sizes = [source.stat().st_size for source in sources]
    if any(size > member_limit for size in sizes) or sum(sizes) > total_limit:
        raise ValueError("loose images exceed the encoded-byte budget")
    total = 0
    written = []
    for index, source in enumerate(sources):
        target = pages_dir / f"{ir.page_id_for(index)}{source.suffix.lower()}"
        count = 0
        created = False
        try:
            with source.open("rb") as reader, target.open("xb") as writer:
                created = True
                while True:
                    budget = min(member_limit - count, total_limit - total)
                    chunk = reader.read(min(1 << 20, budget + 1))
                    if not chunk:
                        break
                    if len(chunk) > budget:
                        raise ValueError("loose image grew beyond its encoded-byte budget")
                    writer.write(chunk)
                    count += len(chunk)
                    total += len(chunk)
        except BaseException:
            # The importer owns this new staging target, never the source.
            if created:
                target.unlink(missing_ok=True)
            raise
        written.append(target)
    return written
