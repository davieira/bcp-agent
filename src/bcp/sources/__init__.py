"""
Story input sources for the BCP Calculator.

Built-in sources are registered on import. Add a new source by implementing
``StorySource`` and registering it here (see docs/usage/story_sources.md).
"""

from .base import (
    SourceAuthError,
    SourceConfigError,
    SourceError,
    SourceNotFoundError,
    SourceQuery,
    Story,
    StorySource,
    parse_filter_args,
)
from .registry import SourceRegistry, get_registry, register
from .service import StoryInputService

# Built-in sources: importing the modules runs @register.
from .file import FileSource  # noqa: F401
from .trello import (  # noqa: F401
    TrelloAuthError,
    TrelloCard,
    TrelloClient,
    TrelloError,
    TrelloNotFoundError,
    TrelloSource,
    card_to_story_markdown,
    parse_trello_board_ref,
    parse_trello_card_ref,
)

__all__ = [
    "FileSource",
    "SourceAuthError",
    "SourceConfigError",
    "SourceError",
    "SourceNotFoundError",
    "SourceQuery",
    "SourceRegistry",
    "Story",
    "StoryInputService",
    "StorySource",
    "TrelloAuthError",
    "TrelloCard",
    "TrelloClient",
    "TrelloError",
    "TrelloNotFoundError",
    "TrelloSource",
    "card_to_story_markdown",
    "get_registry",
    "parse_filter_args",
    "parse_trello_board_ref",
    "parse_trello_card_ref",
    "register",
]
