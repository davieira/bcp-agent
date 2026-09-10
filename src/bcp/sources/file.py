"""
Local filesystem story source.

This is the original BCP input: a markdown (or text) file on disk.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List, Optional

from .base import SourceConfigError, SourceError, SourceNotFoundError, SourceQuery, Story, StorySource
from .registry import register


@register
class FileSource(StorySource):
    """Read user stories from local files or a directory of files."""

    name = "file"
    description = "Local markdown/text user story files"

    @classmethod
    def from_config(cls, logger: Optional[logging.Logger] = None, **kwargs: Any) -> "FileSource":
        return cls(logger=logger)

    @classmethod
    def build_query(cls, args) -> SourceQuery:
        item = getattr(args, "source_id", None) or getattr(args, "story_file", None)
        container = getattr(args, "container", None)
        query = SourceQuery(
            item=item or None,
            container=container or None,
            container_type=getattr(args, "container_type", None) or ("directory" if container else None),
            filters=super().build_query(args).filters,
        )
        if not query.has_target():
            raise SourceConfigError(
                "Provide a path to a user story file, or use --source with another input."
            )
        return query

    def fetch(self, query: SourceQuery) -> List[Story]:
        self.validate_query(query)

        if query.container and (query.container_type or "directory") == "directory":
            return self._read_directory(query.container, query.filters.get("pattern", "*.md"))

        if not query.item:
            raise SourceConfigError("Provide a path to a user story file")

        return [self._read_file(query.item)]

    def _read_file(self, file_path: str) -> Story:
        path = Path(file_path)
        if not path.is_file():
            raise SourceNotFoundError(f"Story file not found: {file_path}")

        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SourceError(f"Error reading story file: {exc}") from exc

        title = next((line.strip() for line in content.splitlines() if line.strip()), path.name)
        return Story(
            id=str(path),
            title=title.lstrip("# ").strip() or path.name,
            content=content,
            source=self.name,
            url=str(path.resolve()),
            metadata={"path": str(path)},
        )

    def _read_directory(self, directory: str, pattern: str) -> List[Story]:
        dir_path = Path(directory)
        if not dir_path.is_dir():
            raise SourceNotFoundError(f"Not a directory: {directory}")

        stories = []
        for file_path in sorted(dir_path.glob(pattern)):
            if file_path.is_file():
                stories.append(self._read_file(str(file_path)))
        if not stories:
            raise SourceNotFoundError(
                f"No story files matching '{pattern}' in directory: {directory}"
            )
        return stories
