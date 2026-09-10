"""
Pluggable story input sources.

A source reads work items from somewhere (a markdown file, Trello, later Jira
or Azure DevOps) and returns normalized ``Story`` objects. The BCP calculator
only ever sees ``story.content``.

To add a new source:

1. Subclass ``StorySource`` in ``src/bcp/sources/<name>.py``
2. Set ``name`` (CLI/API value) and implement ``fetch`` / ``from_config``
3. Optionally override ``configure_cli``, ``build_query``, and ``detect_from_args``
4. Register the class in ``src/bcp/sources/__init__.py``

See ``docs/usage/story_sources.md`` for a complete walkthrough.
"""

from __future__ import annotations

import argparse
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, Optional, Sequence, Tuple


class SourceError(Exception):
    """Base error for story source failures."""


class SourceAuthError(SourceError):
    """Raised when source credentials are missing or rejected."""


class SourceNotFoundError(SourceError):
    """Raised when a requested story or collection cannot be found."""


class SourceConfigError(SourceError):
    """Raised when a source query or configuration is invalid."""


@dataclass
class Story:
    """Normalized user story, independent of the originating system."""

    id: str
    title: str
    content: str
    source: str
    url: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_source_dict(self) -> Dict[str, Any]:
        """Metadata attached to BCP results so callers know where the story came from."""
        payload = {
            "type": self.source,
            "id": self.id,
            "title": self.title,
            "url": self.url,
        }
        payload.update(self.metadata)
        return payload


@dataclass
class SourceQuery:
    """
    Source-agnostic fetch request.

    ``item`` identifies a single story (file path, Trello card URL, Jira key, ...).
    ``container`` identifies a collection (directory, board, list, project, JQL, ...).
    ``container_type`` disambiguates the container when a source supports more than one.
    ``filters`` holds source-specific options (label, list_name, include_closed, ...).
    """

    item: Optional[str] = None
    container: Optional[str] = None
    container_type: Optional[str] = None
    filters: Dict[str, Any] = field(default_factory=dict)

    def has_target(self) -> bool:
        return bool(self.item) or bool(self.container)


def parse_filter_args(values: Optional[Sequence[str]]) -> Dict[str, Any]:
    """Parse repeated CLI ``--filter KEY=VALUE`` arguments into a dictionary."""
    filters: Dict[str, Any] = {}
    for raw in values or []:
        if "=" not in raw:
            raise SourceConfigError(f"Invalid filter '{raw}'. Use KEY=VALUE.")
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise SourceConfigError(f"Invalid filter '{raw}'. Use KEY=VALUE.")
        lowered = value.lower()
        if lowered in {"true", "false"}:
            filters[key] = lowered == "true"
        else:
            filters[key] = value
    return filters


class StorySource(ABC):
    """
    Adapter that loads user stories from an external system or local files.

    Implementations must convert vendor payloads into ``Story.content`` markdown.
    They must not call the BCP calculator.
    """

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    required_env_vars: ClassVar[Tuple[str, ...]] = ()

    def __init__(self, logger: Optional[logging.Logger] = None):
        if not self.name:
            raise SourceConfigError(f"{type(self).__name__} must define a source name")
        self.logger = logger or logging.getLogger(f"bcp.sources.{self.name}")

    @classmethod
    @abstractmethod
    def from_config(cls, logger: Optional[logging.Logger] = None, **kwargs: Any) -> "StorySource":
        """Build a source from environment variables and optional overrides."""

    @abstractmethod
    def fetch(self, query: SourceQuery) -> List[Story]:
        """Fetch one or more stories matching the query."""

    @classmethod
    def configure_cli(cls, parser: argparse.ArgumentParser) -> None:
        """Register source-specific CLI flags. Override in subclasses when needed."""

    @classmethod
    def detect_from_args(cls, args: argparse.Namespace) -> bool:
        """Return True when CLI args clearly belong to this source (used to infer --source)."""
        return False

    @classmethod
    def build_query(cls, args: argparse.Namespace) -> SourceQuery:
        """Map parsed CLI arguments onto a SourceQuery."""
        item = getattr(args, "source_id", None) or None
        if not item and getattr(args, "story_file", None) and getattr(args, "source", None) == cls.name:
            item = args.story_file
        return SourceQuery(
            item=item,
            container=getattr(args, "container", None) or None,
            container_type=getattr(args, "container_type", None) or None,
            filters=parse_filter_args(getattr(args, "source_filters", None)),
        )

    def validate_query(self, query: SourceQuery) -> None:
        """Raise SourceConfigError when the query is not usable by this source."""
        if not query.has_target():
            raise SourceConfigError(
                f"Source '{self.name}' requires --id (or a positional target) "
                "or --container."
            )

    def enrich(self, story: Story, results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Write calculation results back to the originating system.

        Sources that only read (e.g. local files) leave this as a no-op.
        Trello/Jira adapters should comment on the card/issue and update fields.
        """
        return {}

