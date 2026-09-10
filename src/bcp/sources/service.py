"""
Orchestration for loading stories from a source and calculating BCP.

CLI, HTTP API, SDK, and MCP all go through this service so a new source only
needs a ``StorySource`` implementation — not changes in every entry point.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .base import SourceNotFoundError, SourceQuery, Story
from .registry import SourceRegistry, get_registry


class StoryInputService:
    """Load normalized stories from a named source and run BCP calculation."""

    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        registry: Optional[SourceRegistry] = None,
    ):
        self.logger = logger or logging.getLogger("bcp.sources")
        self.registry = registry or get_registry()

    def load_stories(self, source_name: str, query: SourceQuery, **source_kwargs: Any) -> List[Story]:
        source = self.registry.create(source_name, logger=self.logger, **source_kwargs)
        source.validate_query(query)
        stories = source.fetch(query)
        if not stories:
            raise SourceNotFoundError(f"No stories found in source '{source_name}'")
        self.logger.info(f"Loaded {len(stories)} stor{'y' if len(stories) == 1 else 'ies'} from {source_name}")
        return stories

    def process(
        self,
        source_name: str,
        query: SourceQuery,
        calculator: Any,
        write_back: bool = True,
        **source_kwargs: Any,
    ) -> Dict[str, Any]:
        """Load stories, calculate BCP, and optionally write results back to the source."""
        source = self.registry.create(source_name, logger=self.logger, **source_kwargs)
        source.validate_query(query)
        stories = source.fetch(query)
        if not stories:
            raise SourceNotFoundError(f"No stories found in source '{source_name}'")
        self.logger.info(f"Loaded {len(stories)} stor{'y' if len(stories) == 1 else 'ies'} from {source_name}")
        self.logger.info(
            f"[Write-back] {'ON' if write_back else 'OFF'} for source '{source_name}' "
            f"({len(stories)} stor{'y' if len(stories) == 1 else 'ies'})"
        )
        return self.calculate(calculator, stories, source=source, write_back=write_back)

    def calculate(
        self,
        calculator: Any,
        stories: List[Story],
        source: Optional[Any] = None,
        write_back: bool = False,
    ) -> Dict[str, Any]:
        """
        Run BCP calculation for one or more stories.

        A single story returns the calculator payload plus ``source`` metadata.
        Multiple stories return ``{"source", "count", "results": [...]}``.
        """
        if not stories:
            raise SourceNotFoundError("No stories to calculate")

        results = []
        for story in stories:
            self.logger.info(f"Calculating BCP for {story.source} story '{story.title}' ({story.id})")
            try:
                result = calculator.calculate_bcp(story.content)
                result["source"] = story.to_source_dict()
                if write_back and source is not None:
                    self.logger.info(
                        f"[Write-back] Writing BCP to {story.source} '{story.title}' ({story.url or story.id})"
                    )
                    try:
                        summary = source.enrich(story, result) or {}
                        result["write_back"] = summary
                        log_write_back(self.logger, story, summary)
                    except Exception as exc:
                        result["write_back"] = {"ok": False, "error": str(exc)}
                        self.logger.error(
                            f"[Write-back] FAILED '{story.title}' ({story.url or story.id}): {exc}"
                        )
                else:
                    result["write_back"] = {
                        "ok": False,
                        "skipped": True,
                        "reason": "disabled" if not write_back else "source missing",
                    }
                    self.logger.warning(
                        f"[Write-back] SKIPPED '{story.title}' ({story.url or story.id}): "
                        f"{result['write_back']['reason']}"
                    )
                results.append(result)
            except Exception as exc:
                self.logger.error(f"Error calculating BCP for {story.id}: {exc}")
                results.append({"source": story.to_source_dict(), "error": str(exc)})

        if len(results) == 1 and "error" not in results[0]:
            return results[0]

        if len(results) == 1 and "error" in results[0]:
            raise RuntimeError(results[0]["error"])

        return {
            "source": stories[0].source,
            "count": len(results),
            "results": results,
        }


def log_write_back(logger: logging.Logger, story: Story, summary: Dict[str, Any]) -> None:
    """Emit a clear success or failure log for writing results back to a source item."""
    error = summary.get("error")
    target = story.url or story.id
    title = story.title or story.id
    if error or summary.get("ok") is False:
        logger.error(f"[Write-back] FAILED '{title}' ({target}): {error or 'unknown error'}")
        return

    extras = []
    extras.append("comment=yes" if summary.get("comment") else "comment=no")
    fields = summary.get("custom_fields") or []
    extras.append("custom_fields=" + (",".join(fields) if fields else "none"))
    logger.info(f"[Write-back] SUCCESS '{title}' ({target}): {', '.join(extras)}")


