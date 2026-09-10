"""
Trello story source.

Fetches Trello cards and converts them into markdown user stories that the
BCP calculator can analyze.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from .base import SourceAuthError, SourceConfigError, SourceError, SourceNotFoundError, SourceQuery, Story, StorySource
from .registry import register

TRELLO_API_BASE_URL = "https://api.trello.com/1"
CARD_FIELDS = "name,desc,url,shortUrl,shortLink,idList,idBoard,labels,closed,due"

CARD_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?trello\.com/c/([a-zA-Z0-9]+)(?:/.*)?",
    re.IGNORECASE,
)
BOARD_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?trello\.com/b/([a-zA-Z0-9]+)(?:/.*)?",
    re.IGNORECASE,
)


class TrelloError(SourceError):
    """Base error for Trello source failures."""


class TrelloAuthError(TrelloError, SourceAuthError):
    """Raised when Trello credentials are missing or rejected."""


class TrelloNotFoundError(TrelloError, SourceNotFoundError):
    """Raised when a Trello board, list, or card cannot be found."""


@dataclass
class TrelloCard:
    """A Trello card converted into BCP story content."""

    id: str
    name: str
    content: str
    url: str = ""
    short_link: str = ""
    list_id: str = ""
    board_id: str = ""
    closed: bool = False
    labels: List[str] = field(default_factory=list)

    def source_metadata(self) -> Dict[str, Any]:
        """Return metadata describing this Trello card as a story source."""
        return {
            "card_id": self.id,
            "short_link": self.short_link,
            "card_url": self.url,
            "card_name": self.name,
            "list_id": self.list_id,
            "board_id": self.board_id,
            "labels": self.labels,
        }

    def to_story(self) -> Story:
        """Convert this card into a source-agnostic Story."""
        return Story(
            id=self.id,
            title=self.name,
            content=self.content,
            source="trello",
            url=self.url,
            metadata=self.source_metadata(),
        )


def parse_trello_card_ref(value: str) -> str:
    """Extract a Trello card id or shortLink from a URL or raw identifier."""
    if not value or not value.strip():
        raise TrelloError("Trello card id or URL is required")

    raw = value.strip()
    match = CARD_URL_RE.search(raw)
    if match:
        return match.group(1)

    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc and "trello.com" not in parsed.netloc.lower():
        raise TrelloError(f"Not a Trello card URL: {value}")

    return raw


def parse_trello_board_ref(value: str) -> str:
    """Extract a Trello board id or shortLink from a URL or raw identifier."""
    if not value or not value.strip():
        raise TrelloError("Trello board id or URL is required")

    raw = value.strip()
    match = BOARD_URL_RE.search(raw)
    if match:
        return match.group(1)

    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc and "trello.com" not in parsed.netloc.lower():
        raise TrelloError(f"Not a Trello board URL: {value}")

    return raw


def card_to_story_markdown(
    card: Dict[str, Any],
    custom_field_defs: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    """Convert a Trello card payload into markdown suitable for BCP analysis."""
    parts: List[str] = []
    name = (card.get("name") or "Untitled Trello Card").strip()
    parts.append(f"# {name}")
    parts.append("")

    description = strip_bcp_description((card.get("desc") or "").strip())
    if description:
        parts.append(description)
        parts.append("")

    label_names = [
        label.get("name")
        for label in card.get("labels") or []
        if label.get("name")
    ]
    if label_names:
        parts.append("## Labels")
        for label_name in label_names:
            parts.append(f"- {label_name}")
        parts.append("")

    checklists = card.get("checklists") or []
    if checklists:
        parts.append("## Checklists")
        for checklist in checklists:
            checklist_name = (checklist.get("name") or "Checklist").strip()
            parts.append(f"### {checklist_name}")
            items = sorted(
                checklist.get("checkItems") or [],
                key=lambda item: item.get("pos", 0),
            )
            for item in items:
                state = item.get("state", "incomplete")
                mark = "x" if state == "complete" else " "
                item_name = (item.get("name") or "").strip()
                parts.append(f"- [{mark}] {item_name}")
            parts.append("")

    custom_fields = _format_custom_fields(
        card.get("customFieldItems") or [],
        custom_field_defs or {},
    )
    if custom_fields:
        parts.append("## Custom Fields")
        for field_name, field_value in custom_fields:
            parts.append(f"- {field_name}: {field_value}")
        parts.append("")

    url = card.get("url") or card.get("shortUrl") or ""
    if url:
        parts.append("## Source")
        parts.append(f"- Trello: {url}")
        parts.append("")

    return "\n".join(parts).strip() + "\n"


def _format_custom_fields(
    items: Iterable[Dict[str, Any]],
    definitions: Dict[str, Dict[str, Any]],
) -> List[tuple]:
    formatted = []
    for item in items:
        field_id = item.get("idCustomField")
        definition = definitions.get(field_id, {})
        field_name = definition.get("name") or field_id
        if not field_name or _is_score_custom_field(field_name):
            continue

        value = item.get("value") or {}
        if "text" in value:
            display = value["text"]
        elif "number" in value:
            display = str(value["number"])
        elif "date" in value:
            display = str(value["date"])
        elif "checked" in value:
            display = "Yes" if str(value["checked"]).lower() in {"true", "1"} else "No"
        elif item.get("idValue"):
            display = _option_name(definition, item["idValue"])
        else:
            continue

        if display is None or str(display).strip() == "":
            continue
        formatted.append((field_name, display))
    return formatted


def _option_name(definition: Dict[str, Any], option_id: str) -> str:
    for option in definition.get("options") or []:
        if option.get("id") == option_id:
            return option.get("value", {}).get("text") or option_id
    return option_id


CUSTOM_FIELD_ALIASES = {
    "bcp": ("bcp", "total bcp", "total_bcp", "business complexity points"),
    "maturity": ("maturity", "maturidade", "story maturity"),
    "invest": ("invest", "invest maturity"),
}

CUSTOM_FIELD_CREATE = {
    "bcp": {"name": "BCP", "type": "number"},
    "maturity": {"name": "Maturidade", "type": "number"},
    "invest": {"name": "INVEST", "type": "number"},
}


def _is_score_custom_field(name: str) -> bool:
    """True for BCP score fields that must not pollute the story markdown."""
    wanted = {alias.lower() for aliases in CUSTOM_FIELD_ALIASES.values() for alias in aliases}
    return (name or "").strip().lower() in wanted


def format_bcp_comment(results: Dict[str, Any]) -> str:
    """Build a Trello markdown comment with the BCP summary."""
    steps = results.get("steps") or {}
    maturity = _step_score(steps, "Story Maturity Complexity")
    invest = _step_score(steps, "Story INVEST Maturity")
    maturity_class = _step_field(steps, "Story Maturity Complexity", "classification")
    invest_class = _step_field(steps, "Story INVEST Maturity", "classification")

    lines = [
        "## BCP Calculator",
        "",
        f"**Total BCP:** {results.get('total_bcp', 0)}",
        "",
    ]
    breakdown = results.get("breakdown") or {}
    if breakdown:
        lines.append("**Componentes**")
        for name, score in breakdown.items():
            lines.append(f"- {name}: {score}")
        lines.append("")
    lines.append(f"**Maturidade:** {maturity}" + (f" ({maturity_class})" if maturity_class else ""))
    lines.append(f"**INVEST:** {invest}" + (f" ({invest_class})" if invest_class else ""))
    return "\n".join(lines).strip() + "\n"


BCP_BLOCK_START = "<!-- bcp-calculator:start -->"
BCP_BLOCK_END = "<!-- bcp-calculator:end -->"


def strip_bcp_description(existing: str) -> str:
    """Remove a previously injected BCP section from a Trello card description."""
    existing = existing or ""
    if BCP_BLOCK_START not in existing or BCP_BLOCK_END not in existing:
        return existing
    before, rest = existing.split(BCP_BLOCK_START, 1)
    _, after = rest.split(BCP_BLOCK_END, 1)
    return (before.rstrip() + "\n" + after.lstrip("\n")).strip()


def _step_score(steps: Dict[str, Any], step_name: str) -> Any:
    step = steps.get(step_name) or {}
    if isinstance(step, dict):
        return step.get("score", step.get("total", 0))
    return 0


def _step_field(steps: Dict[str, Any], step_name: str, field_name: str) -> str:
    step = steps.get(step_name) or {}
    if isinstance(step, dict):
        return str(step.get(field_name) or "")
    return ""


class TrelloClient:
    """Client for reading Trello cards as BCP user stories."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        token: Optional[str] = None,
        base_url: Optional[str] = None,
        session: Optional[requests.Session] = None,
        timeout: int = 30,
        logger: Optional[logging.Logger] = None,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get("TRELLO_API_KEY")
        self.token = token if token is not None else os.environ.get("TRELLO_TOKEN")
        self.base_url = (
            base_url
            or os.environ.get("TRELLO_API_BASE_URL")
            or TRELLO_API_BASE_URL
        ).rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.logger = logger or logging.getLogger(__name__)

    def fetch_card(self, card_ref: str) -> TrelloCard:
        """Fetch a single Trello card by id, shortLink, or URL."""
        card_id = parse_trello_card_ref(card_ref)
        payload = self._request(f"cards/{card_id}", self._card_params())
        field_defs = self._fetch_custom_field_defs(payload.get("idBoard"))
        return self._to_card(payload, field_defs)

    def fetch_list_cards(
        self,
        list_id: str,
        include_closed: bool = False,
        label: Optional[str] = None,
    ) -> List[TrelloCard]:
        """Fetch open cards from a Trello list."""
        if not list_id or not list_id.strip():
            raise TrelloError("Trello list id is required")

        payloads = self._fetch_card_payloads(f"lists/{list_id.strip()}/cards", include_closed)
        board_id = payloads[0].get("idBoard") if payloads else None
        field_defs = self._fetch_custom_field_defs(board_id)
        cards = [self._to_card(payload, field_defs) for payload in payloads]
        return self._filter_by_label(cards, label)

    def fetch_board_cards(
        self,
        board_ref: str,
        list_name: Optional[str] = None,
        include_closed: bool = False,
        label: Optional[str] = None,
    ) -> List[TrelloCard]:
        """Fetch cards from a Trello board, optionally filtered by list name and label."""
        board_id = parse_trello_board_ref(board_ref)

        if list_name:
            lists = self._request(f"boards/{board_id}/lists", {"fields": "name,id,closed"})
            matching = [
                lst
                for lst in lists
                if (lst.get("name") or "").strip().lower() == list_name.strip().lower()
            ]
            if not matching:
                available = ", ".join(
                    (lst.get("name") or "").strip() or lst.get("id", "") for lst in lists
                ) or "(none)"
                raise TrelloNotFoundError(
                    f"List '{list_name}' not found on board. Available lists: {available}"
                )
            payloads: List[Dict[str, Any]] = []
            for lst in matching:
                payloads.extend(
                    self._fetch_card_payloads(f"lists/{lst['id']}/cards", include_closed)
                )
        else:
            payloads = self._fetch_card_payloads(f"boards/{board_id}/cards", include_closed)

        field_defs = self._fetch_custom_field_defs(board_id)
        cards = [self._to_card(payload, field_defs) for payload in payloads]
        return self._filter_by_label(cards, label)

    def _card_params(self, include_closed: Optional[bool] = None) -> Dict[str, str]:
        params = {
            "fields": CARD_FIELDS,
            "checklists": "all",
            "customFieldItems": "true",
        }
        if include_closed is not None:
            params["filter"] = "all" if include_closed else "open"
        return params

    def _fetch_card_payloads(self, path: str, include_closed: bool) -> List[Dict[str, Any]]:
        payloads = self._request(path, self._card_params(include_closed=include_closed))
        if not isinstance(payloads, list):
            raise TrelloError(f"Unexpected Trello response for {path}")
        return payloads

    def _fetch_custom_field_defs(self, board_id: Optional[str]) -> Dict[str, Dict[str, Any]]:
        if not board_id:
            return {}
        try:
            definitions = self._request(f"boards/{board_id}/customFields")
        except TrelloError as exc:
            self.logger.debug(f"Could not load Trello custom fields: {exc}")
            return {}

        return {item.get("id"): item for item in definitions if item.get("id")}

    def _to_card(
        self,
        payload: Dict[str, Any],
        field_defs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> TrelloCard:
        labels = [
            label.get("name")
            for label in payload.get("labels") or []
            if label.get("name")
        ]
        return TrelloCard(
            id=payload.get("id") or "",
            name=(payload.get("name") or "Untitled Trello Card").strip(),
            content=card_to_story_markdown(payload, field_defs),
            url=payload.get("url") or payload.get("shortUrl") or "",
            short_link=payload.get("shortLink") or "",
            list_id=payload.get("idList") or "",
            board_id=payload.get("idBoard") or "",
            closed=bool(payload.get("closed")),
            labels=labels,
        )

    def _filter_by_label(self, cards: List[TrelloCard], label: Optional[str]) -> List[TrelloCard]:
        if not label:
            return cards
        expected = label.strip().lower()
        return [
            card
            for card in cards
            if expected in [item.lower() for item in card.labels]
        ]

    def add_comment(self, card_id: str, text: str) -> Dict[str, Any]:
        """Post a comment on a Trello card. Token must include the write scope."""
        if not card_id:
            raise TrelloError("Trello card id is required to add a comment")
        return self._request(
            f"cards/{card_id}/actions/comments",
            method="POST",
            params={"text": text},
        )

    def get_card_description(self, card_id: str) -> str:
        payload = self._request(f"cards/{card_id}", params={"fields": "desc"})
        return (payload or {}).get("desc") or ""

    def update_card_description(self, card_id: str, description: str) -> Dict[str, Any]:
        """Replace the card description. Prefer form body so long markdown is not truncated."""
        return self._request(
            f"cards/{card_id}",
            method="PUT",
            data={"desc": description},
        )

    def update_custom_field(self, card_id: str, field_id: str, field_type: str, value: Any) -> Dict[str, Any]:
        """Set a custom field value on a card."""
        if field_type == "number":
            payload = {"value": {"number": str(value)}}
        elif field_type == "text":
            payload = {"value": {"text": str(value)}}
        elif field_type == "checkbox":
            payload = {"value": {"checked": "true" if value else "false"}}
        else:
            payload = {"value": {"text": str(value)}}
        return self._request(
            f"cards/{card_id}/customField/{field_id}/item",
            method="PUT",
            json_body=payload,
        )

    def create_custom_field(self, board_id: str, name: str, field_type: str = "number") -> Dict[str, Any]:
        """Create a board custom field so BCP scores can live on the card front."""
        return self._request(
            "customFields",
            method="POST",
            json_body={
                "idModel": board_id,
                "modelType": "board",
                "name": name,
                "type": field_type,
                "pos": "bottom",
                "display": {"cardFront": True},
            },
        )

    def _request(
        self,
        path: str,
        params: Optional[Dict[str, str]] = None,
        method: str = "GET",
        json_body: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, str]] = None,
    ) -> Any:
        if not self.api_key or not self.token:
            raise TrelloAuthError(
                "Trello credentials are missing. Set TRELLO_API_KEY and TRELLO_TOKEN."
            )

        url = f"{self.base_url}/{path.lstrip('/')}"
        query = {"key": self.api_key, "token": self.token}
        if params:
            query.update(params)

        try:
            response = self.session.request(
                method,
                url,
                params=query,
                json=json_body,
                data=data,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise TrelloError(f"Failed to reach Trello API: {exc}") from exc

        if response.status_code in (401, 403):
            hint = ""
            if method.upper() != "GET":
                hint = (
                    " Token must include write scope. Generate one at "
                    "https://trello.com/1/authorize?expiration=never&scope=read,write"
                    "&response_type=token&name=BCP-Calculator&key=YOUR_API_KEY"
                )
            raise TrelloAuthError(
                "Trello authentication failed. Check TRELLO_API_KEY and TRELLO_TOKEN."
                + hint
            )
        if response.status_code == 404:
            raise TrelloNotFoundError(f"Trello resource not found: {path}")
        if response.status_code == 429:
            raise TrelloError("Trello API rate limit exceeded. Try again later.")
        if not response.ok:
            body = (response.text or "")[:200]
            raise TrelloError(f"Trello API error {response.status_code}: {body}")

        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise TrelloError("Trello API returned a non-JSON response") from exc


@register
class TrelloSource(StorySource):
    """Load user stories from Trello cards, lists, or boards."""

    name = "trello"
    description = "Trello cards as user stories"
    required_env_vars = ("TRELLO_API_KEY", "TRELLO_TOKEN")

    def __init__(
        self,
        client: Optional[TrelloClient] = None,
        logger: Optional[logging.Logger] = None,
        write_custom_fields: bool = False,
    ):
        super().__init__(logger=logger)
        self.client = client or TrelloClient(logger=self.logger)
        self.write_custom_fields = write_custom_fields

    @classmethod
    def from_config(cls, logger: Optional[logging.Logger] = None, **kwargs: Any) -> "TrelloSource":
        write_custom_fields = bool(kwargs.pop("write_custom_fields", False))
        client = kwargs.pop("client", None) or TrelloClient(
            api_key=kwargs.pop("api_key", None),
            token=kwargs.pop("token", None),
            base_url=kwargs.pop("base_url", None),
            session=kwargs.pop("session", None),
            logger=logger,
        )
        return cls(client=client, logger=logger, write_custom_fields=write_custom_fields)

    @classmethod
    def configure_cli(cls, parser) -> None:
        group = parser.add_argument_group("Trello source options")
        group.add_argument(
            "--trello-list",
            help="Trello list id. Calculates BCP for every open card in the list.",
        )
        group.add_argument(
            "--trello-board",
            help="Trello board id or URL. Calculates BCP for open cards on the board.",
        )
        group.add_argument(
            "--trello-list-name",
            help="When using a board, only include cards from this list name.",
        )
        group.add_argument(
            "--trello-label",
            help="Only include cards that have this label name.",
        )
        group.add_argument(
            "--trello-include-closed",
            action="store_true",
            help="Include archived/closed Trello cards.",
        )
        group.add_argument(
            "--trello-custom-fields",
            action="store_true",
            help=(
                "Create/update board custom fields BCP, Maturidade, and INVEST. "
                "Requires Trello Premium (Custom Fields). Default: comment only."
            ),
        )

    @classmethod
    def detect_from_args(cls, args) -> bool:
        return bool(
            getattr(args, "trello_list", None)
            or getattr(args, "trello_board", None)
            or getattr(args, "trello_list_name", None)
            or getattr(args, "trello_label", None)
            or getattr(args, "trello_include_closed", False)
        )

    @classmethod
    def build_query(cls, args) -> SourceQuery:
        query = super().build_query(args)

        if getattr(args, "story_file", None) and not query.item and not query.container:
            query.item = args.story_file

        targets = []
        if query.item:
            targets.append("id")
        if getattr(args, "trello_list", None):
            targets.append("trello-list")
        if getattr(args, "trello_board", None):
            targets.append("trello-board")
        if query.container and not getattr(args, "trello_list", None) and not getattr(args, "trello_board", None):
            targets.append("container")

        if len(targets) > 1:
            raise SourceConfigError(
                "Use only one Trello target: a card id/URL, --trello-list, or --trello-board."
            )
        if not targets:
            raise SourceConfigError(
                "Provide a Trello card id/URL, --trello-list, or --trello-board."
            )

        if args.trello_list:
            query.container = args.trello_list
            query.container_type = "list"
            query.item = None
        elif args.trello_board:
            query.container = args.trello_board
            query.container_type = "board"
            query.item = None
        elif query.container and not query.container_type:
            raise SourceConfigError(
                "When using --container with Trello, pass --container-type list or board."
            )

        if getattr(args, "trello_list_name", None):
            query.filters["list_name"] = args.trello_list_name
        if getattr(args, "trello_label", None):
            query.filters["label"] = args.trello_label
        if getattr(args, "trello_include_closed", False):
            query.filters["include_closed"] = True

        if query.filters.get("list_name") and query.container_type != "board":
            raise SourceConfigError("--trello-list-name can only be used with a Trello board.")

        return query

    def validate_query(self, query: SourceQuery) -> None:
        if query.item:
            return
        if not query.container:
            raise SourceConfigError(
                "Provide a Trello card id/URL, a list id, or a board id/URL."
            )
        container_type = (query.container_type or "").lower()
        if container_type not in {"list", "board"}:
            raise SourceConfigError(
                "Trello container_type must be 'list' or 'board'."
            )
        if query.filters.get("list_name") and container_type != "board":
            raise SourceConfigError("list_name can only be used with a Trello board.")

    def fetch(self, query: SourceQuery) -> List[Story]:
        self.validate_query(query)
        include_closed = bool(query.filters.get("include_closed", False))
        label = query.filters.get("label")

        if query.item:
            card = self.client.fetch_card(query.item)
            return [card.to_story()]

        container_type = (query.container_type or "").lower()
        if container_type == "list":
            cards = self.client.fetch_list_cards(
                query.container,
                include_closed=include_closed,
                label=label,
            )
        else:
            cards = self.client.fetch_board_cards(
                query.container,
                list_name=query.filters.get("list_name"),
                include_closed=include_closed,
                label=label,
            )

        return [card.to_story() for card in cards]

    def enrich(self, story: Story, results: Dict[str, Any]) -> Dict[str, Any]:
        """Write BCP to a Trello comment; custom fields only when explicitly enabled."""
        card_id = story.id or (story.metadata or {}).get("card_id")
        if not card_id:
            raise TrelloError("Cannot enrich Trello card without a card id")

        summary = {
            "ok": False,
            "comment": False,
            "custom_fields": [],
        }

        current_desc = self.client.get_card_description(card_id)
        cleaned_desc = strip_bcp_description(current_desc)
        if cleaned_desc.strip() != (current_desc or "").strip():
            self.client.update_card_description(card_id, cleaned_desc)
            self.logger.info(
                f"[Write-back] Removed BCP block from description of '{story.title}'"
            )

        self.client.add_comment(card_id, format_bcp_comment(results))
        summary["comment"] = True

        if not self.write_custom_fields:
            self.logger.info(
                "[Write-back] Custom fields skipped; pass --trello-custom-fields to create/update them"
            )
            summary["ok"] = True
            return summary

        board_id = (story.metadata or {}).get("board_id")
        field_defs = self._ensure_score_fields(board_id) if board_id else {}
        values = {
            "bcp": results.get("total_bcp", 0),
            "maturity": _step_score(results.get("steps") or {}, "Story Maturity Complexity"),
            "invest": _step_score(results.get("steps") or {}, "Story INVEST Maturity"),
        }
        for key, value in values.items():
            definition = _find_custom_field(field_defs, CUSTOM_FIELD_ALIASES[key])
            if not definition:
                continue
            self.client.update_custom_field(
                card_id,
                definition["id"],
                definition.get("type") or "number",
                value,
            )
            summary["custom_fields"].append(definition.get("name") or key)
        summary["ok"] = True
        return summary

    def _ensure_score_fields(self, board_id: str) -> Dict[str, Dict[str, Any]]:
        """Reuse BCP/Maturidade/INVEST custom fields, creating them on the board if needed."""
        definitions = self.client._fetch_custom_field_defs(board_id)
        for key, spec in CUSTOM_FIELD_CREATE.items():
            if _find_custom_field(definitions, CUSTOM_FIELD_ALIASES[key]):
                continue
            try:
                created = self.client.create_custom_field(board_id, spec["name"], spec["type"])
            except TrelloError as exc:
                self.logger.warning(
                    f"[Write-back] Could not create custom field '{spec['name']}': {exc}"
                )
                continue
            if created and created.get("id"):
                definitions[created["id"]] = created
                self.logger.info(f"[Write-back] Created custom field '{spec['name']}' on the board")
        return definitions


def _find_custom_field(
    definitions: Dict[str, Dict[str, Any]],
    aliases: Tuple[str, ...],
) -> Optional[Dict[str, Any]]:
    wanted = {alias.lower() for alias in aliases}
    for definition in definitions.values():
        name = (definition.get("name") or "").strip().lower()
        if name in wanted:
            return definition
    return None

