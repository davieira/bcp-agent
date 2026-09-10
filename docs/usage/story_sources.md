# Story Input Sources

The BCP Calculator loads user stories through a **source adapter**. The calculator
itself only ever receives markdown `Story.content`. Trello, local files, and a
future Jira or Azure DevOps connector all implement the same interface.

## Built-in sources

| Source | `--source` value | Single story | Collection |
|---|---|---|---|
| Local file | `file` (default) | file path | directory |
| Trello | `trello` | card id or URL | list id or board id/URL |

## CLI

File (unchanged):

```bash
python run_cli.py tests/data/story1.md
```

Trello card:

```bash
python run_cli.py --source trello --id https://trello.com/c/abc123
python run_cli.py https://trello.com/c/abc123 --source trello
```

Trello list or board:

```bash
python run_cli.py --trello-list LIST_ID
python run_cli.py --trello-board https://trello.com/b/shortLink --trello-list-name "Ready" --trello-label Story
```

By default the calculator **writes a markdown comment** on each Trello card (total BCP, component breakdown, maturity and INVEST). The story **description is never used for scores**. If a previous run injected a BCP block into the description, that block is stripped.

Custom fields require a Trello plan that includes them (Premium). They are **off by default**. Pass `--trello-custom-fields` to create/update `BCP`, `Maturidade`, and `INVEST` on the board and set the values on the card:

```bash
python run_cli.py --trello-board https://trello.com/b/shortLink --trello-custom-fields
```

The Trello token must include the **write** scope. Generate one with:

```
https://trello.com/1/authorize?expiration=never&scope=read,write&response_type=token&name=BCP-Calculator&key=YOUR_API_KEY
```

To only print JSON and skip updating cards:

```bash
python run_cli.py --trello-board https://trello.com/b/nKfyqkkG/home-automation --no-write-back
```

Trello flags imply `--source trello`. Generic flags work for every source:

| Flag | Meaning |
|---|---|
| `--source` | Adapter name (`file`, `trello`, later `jira`, ...) |
| `--id` | One story (path, card URL, issue key, work item id) |
| `--container` | A collection (directory, board, list, project, query) |
| `--container-type` | Disambiguates `--container` (`board`, `list`, `directory`, ...) |
| `--filter KEY=VALUE` | Source-specific options (repeatable) |

## HTTP API

`POST /calculate` still accepts inline story text.

`GET /sources` lists registered adapters.

`POST /calculate/source` loads stories from an adapter:

```json
{
  "source": "trello",
  "id": "https://trello.com/c/abc123",
  "provider": "openai",
  "write_custom_fields": false
}
```

```json
{
  "source": "trello",
  "container": "https://trello.com/b/shortLink",
  "container_type": "board",
  "filters": {
    "list_name": "Ready",
    "label": "Story"
  },
  "provider": "openai"
}
```

## Python SDK

```python
from src.sdk import BCPClient

client = BCPClient(provider="openai")

client.calculate_from_source("trello", item="https://trello.com/c/abc123")

client.calculate_from_source(
    "trello",
    container="https://trello.com/b/shortLink",
    container_type="board",
    filters={"list_name": "Ready"},
    write_custom_fields=True,
)
```

## Trello setup

1. Create an API key at [https://trello.com/power-ups/admin](https://trello.com/power-ups/admin)
2. Generate a token for that key
3. Add the values to `.env`:

```env
TRELLO_API_KEY=your_trello_key
TRELLO_TOKEN=your_trello_token
```

A card becomes markdown using its title, description, labels, checklists
(acceptance criteria), custom fields, and URL.

## Adding a new source (Jira, Azure DevOps, ...)

Implement `StorySource` and register it. No changes are required in the BCP
calculator, CLI loop, HTTP job runner, or SDK beyond importing the new module.

```python
# src/bcp/sources/jira.py
from typing import Any, List, Optional
import logging

from .base import SourceQuery, Story, StorySource
from .registry import register


@register
class JiraSource(StorySource):
    name = "jira"
    description = "Jira issues as user stories"
    required_env_vars = ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN")

    @classmethod
    def from_config(cls, logger: Optional[logging.Logger] = None, **kwargs: Any) -> "JiraSource":
        return cls(logger=logger)

    @classmethod
    def configure_cli(cls, parser) -> None:
        group = parser.add_argument_group("Jira source options")
        group.add_argument("--jql", help="Jira Query Language string")

    @classmethod
    def detect_from_args(cls, args) -> bool:
        return bool(getattr(args, "jql", None))

    @classmethod
    def build_query(cls, args) -> SourceQuery:
        query = super().build_query(args)
        if getattr(args, "jql", None):
            query.container = args.jql
            query.container_type = "jql"
        return query

    def fetch(self, query: SourceQuery) -> List[Story]:
        self.validate_query(query)
        # 1. Call the vendor API
        # 2. Map each issue to markdown
        # 3. Return Story(id=..., title=..., content=markdown, source=self.name, url=...)
        raise NotImplementedError
```

Then import the class in `src/bcp/sources/__init__.py` so it is registered at
startup:

```python
from .jira import JiraSource  # noqa: F401
```

After that, these work without touching `main.py` or the calculator:

```bash
python run_cli.py --source jira --id PROJ-123
python run_cli.py --source jira --jql "project = PROJ AND sprint in openSprints()"
```

```python
client.calculate_from_source("jira", item="PROJ-123")
```

```http
POST /calculate/source
{"source": "jira", "id": "PROJ-123"}
```

### Contract

- `Story.content` must be the markdown the prompts already understand
- `fetch()` returns one or more `Story` objects and must not call the LLM
- Use `SourceAuthError`, `SourceNotFoundError`, and `SourceConfigError` for failures
- Credentials come from environment variables (and optional `from_config` kwargs)
- Collection fetches are allowed; `StoryInputService` runs BCP per story
