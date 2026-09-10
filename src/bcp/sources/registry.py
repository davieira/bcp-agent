"""
Registry of story input sources.

Built-in sources register themselves at import time. A later Jira or Azure
DevOps adapter is added by subclassing ``StorySource`` and calling
``get_registry().register(TheNewSource)``.
"""

from __future__ import annotations

import argparse
from typing import Dict, Iterable, List, Type

from .base import SourceConfigError, StorySource


class SourceRegistry:
    """Name-to-class map for pluggable story sources."""

    def __init__(self) -> None:
        self._sources: Dict[str, Type[StorySource]] = {}

    def register(self, source_cls: Type[StorySource]) -> Type[StorySource]:
        name = getattr(source_cls, "name", "") or ""
        if not name:
            raise SourceConfigError(f"{source_cls.__name__} must define a class attribute 'name'")
        self._sources[name] = source_cls
        return source_cls

    def get(self, name: str) -> Type[StorySource]:
        if name not in self._sources:
            available = ", ".join(self.names()) or "(none)"
            raise SourceConfigError(
                f"Unknown story source '{name}'. Available sources: {available}"
            )
        return self._sources[name]

    def create(self, name: str, **kwargs) -> StorySource:
        return self.get(name).from_config(**kwargs)

    def names(self) -> List[str]:
        return sorted(self._sources.keys())

    def classes(self) -> Iterable[Type[StorySource]]:
        return self._sources.values()

    def infer_source_name(self, args: argparse.Namespace, default: str = "file") -> str:
        """Pick a source from --source, or infer it from source-specific CLI flags."""
        explicit = getattr(args, "source", None)
        if explicit and explicit != default:
            return explicit

        matches = [
            cls.name
            for cls in self._sources.values()
            if cls.name != default and cls.detect_from_args(args)
        ]
        if len(matches) > 1:
            raise SourceConfigError(
                f"Ambiguous story source flags for: {', '.join(matches)}. "
                "Pass --source explicitly."
            )
        if len(matches) == 1:
            return matches[0]
        return explicit or default

    def configure_cli(self, parser: argparse.ArgumentParser) -> None:
        for source_cls in self._sources.values():
            source_cls.configure_cli(parser)


_REGISTRY = SourceRegistry()


def get_registry() -> SourceRegistry:
    return _REGISTRY


def register(source_cls: Type[StorySource]) -> Type[StorySource]:
    """Decorator/helper to register a StorySource class on the default registry."""
    return _REGISTRY.register(source_cls)
