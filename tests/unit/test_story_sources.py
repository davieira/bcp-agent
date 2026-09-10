import argparse
import logging
import re

import pytest

from bcp.sources import (
    FileSource,
    SourceAuthError,
    SourceConfigError,
    SourceNotFoundError,
    SourceQuery,
    SourceRegistry,
    Story,
    StoryInputService,
    StorySource,
    TrelloSource,
    card_to_story_markdown,
    get_registry,
    parse_filter_args,
    parse_trello_board_ref,
    parse_trello_card_ref,
)
from bcp.sources.trello import format_bcp_comment, strip_bcp_description
from src.main import format_results_json, parse_arguments


CARD_PAYLOAD = {
    "id": "card1",
    "name": "Pagamento automático",
    "desc": "Eu, ENQUANTO cliente, DESEJO configurar pagamento automático.",
    "url": "https://trello.com/c/abc123/pagamento",
    "shortUrl": "https://trello.com/c/abc123",
    "shortLink": "abc123",
    "idList": "list1",
    "idBoard": "board1",
    "closed": False,
    "labels": [{"name": "Story", "color": "blue"}, {"name": "", "color": "green"}],
    "checklists": [
        {
            "name": "Critérios de aceite",
            "checkItems": [
                {"name": "Configurar conta", "state": "incomplete", "pos": 2},
                {"name": "Receber confirmação", "state": "complete", "pos": 1},
            ],
        }
    ],
    "customFieldItems": [
        {
            "idCustomField": "cf1",
            "value": {"text": "Alta"},
        }
    ],
}


class FakeSource(StorySource):
    name = "fake"
    description = "In-memory source used to prove the registry is extensible"

    def __init__(self, logger=None, stories=None):
        super().__init__(logger=logger)
        self._stories = stories or []

    @classmethod
    def from_config(cls, logger=None, **kwargs):
        return cls(logger=logger, stories=kwargs.get("stories"))

    def fetch(self, query: SourceQuery):
        if query.item:
            return [
                story for story in self._stories if story.id == query.item
            ] or [
                Story(id=query.item, title=query.item, content=f"# {query.item}\n", source=self.name)
            ]
        return list(self._stories)


def test_registry_includes_builtin_sources():
    names = get_registry().names()
    assert "file" in names
    assert "trello" in names


def test_registry_can_register_a_new_source():
    registry = SourceRegistry()
    registry.register(FakeSource)
    source = registry.create("fake", stories=[Story(id="1", title="A", content="A", source="fake")])
    stories = source.fetch(SourceQuery(container="all"))
    assert stories[0].title == "A"


def test_unknown_source_raises():
    registry = SourceRegistry()
    with pytest.raises(SourceConfigError, match="Unknown story source"):
        registry.get("jira")


def test_parse_filter_args():
    assert parse_filter_args(["label=Story", "include_closed=true"]) == {
        "label": "Story",
        "include_closed": True,
    }
    with pytest.raises(SourceConfigError):
        parse_filter_args(["invalid"])


def test_file_source_reads_markdown(tmp_path):
    story_file = tmp_path / "story.md"
    story_file.write_text("# Minha história\n\nConteúdo da história.\n", encoding="utf-8")

    source = FileSource()
    stories = source.fetch(SourceQuery(item=str(story_file)))

    assert len(stories) == 1
    assert stories[0].source == "file"
    assert stories[0].title == "Minha história"
    assert "Conteúdo da história" in stories[0].content


def test_file_source_reads_directory(tmp_path):
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\n", encoding="utf-8")
    (tmp_path / "skip.txt").write_text("nope", encoding="utf-8")

    stories = FileSource().fetch(
        SourceQuery(container=str(tmp_path), container_type="directory", filters={"pattern": "*.md"})
    )
    assert [story.title for story in stories] == ["A", "B"]


def test_file_source_missing_file(tmp_path):
    with pytest.raises(SourceNotFoundError):
        FileSource().fetch(SourceQuery(item=str(tmp_path / "missing.md")))


def test_parse_trello_refs():
    assert parse_trello_card_ref("https://trello.com/c/abc123/my-card") == "abc123"
    assert parse_trello_card_ref("abc123") == "abc123"
    assert parse_trello_board_ref("https://trello.com/b/board99/kanban") == "board99"


def test_card_to_story_markdown_includes_description_and_checklists():
    markdown = card_to_story_markdown(
        CARD_PAYLOAD,
        custom_field_defs={"cf1": {"name": "Prioridade", "type": "text"}},
    )
    assert markdown.startswith("# Pagamento automático")
    assert "configurar pagamento automático" in markdown
    assert "- Story" in markdown
    assert "- [x] Receber confirmação" in markdown
    assert "- [ ] Configurar conta" in markdown
    assert "- Prioridade: Alta" in markdown
    assert "https://trello.com/c/abc123/pagamento" in markdown


def _mock_trello(requests_mock):
    requests_mock.get(
        re.compile(r"https://api\.trello\.com/1/cards/abc123"),
        json=CARD_PAYLOAD,
    )
    requests_mock.get(
        re.compile(r"https://api\.trello\.com/1/boards/board1/customFields"),
        json=[{"id": "cf1", "name": "Prioridade", "type": "text"}],
    )
    requests_mock.get(
        re.compile(r"https://api\.trello\.com/1/lists/list1/cards"),
        json=[CARD_PAYLOAD],
    )
    requests_mock.get(
        re.compile(r"https://api\.trello\.com/1/boards/board1/cards"),
        json=[CARD_PAYLOAD],
    )
    requests_mock.get(
        re.compile(r"https://api\.trello\.com/1/boards/board1/lists"),
        json=[{"id": "list1", "name": "Ready", "closed": False}],
    )


def test_trello_source_fetches_card(requests_mock, monkeypatch):
    monkeypatch.setenv("TRELLO_API_KEY", "key")
    monkeypatch.setenv("TRELLO_TOKEN", "token")
    _mock_trello(requests_mock)

    stories = TrelloSource.from_config().fetch(SourceQuery(item="https://trello.com/c/abc123"))
    assert len(stories) == 1
    assert stories[0].source == "trello"
    assert stories[0].title == "Pagamento automático"
    assert "Critérios de aceite" in stories[0].content
    assert stories[0].metadata["card_id"] == "card1"


def test_trello_source_fetches_board_filtered_by_list_name(requests_mock, monkeypatch):
    monkeypatch.setenv("TRELLO_API_KEY", "key")
    monkeypatch.setenv("TRELLO_TOKEN", "token")
    _mock_trello(requests_mock)

    stories = TrelloSource.from_config().fetch(
        SourceQuery(
            container="https://trello.com/b/board1",
            container_type="board",
            filters={"list_name": "Ready", "label": "Story"},
        )
    )
    assert len(stories) == 1
    assert stories[0].id == "card1"


def test_trello_source_requires_credentials(monkeypatch):
    monkeypatch.delenv("TRELLO_API_KEY", raising=False)
    monkeypatch.delenv("TRELLO_TOKEN", raising=False)
    with pytest.raises(SourceAuthError):
        TrelloSource.from_config().fetch(SourceQuery(item="abc123"))


def test_trello_build_query_from_cli_flags():
    args = argparse.Namespace(
        source="trello",
        source_id=None,
        story_file=None,
        container=None,
        container_type=None,
        source_filters=["label=Story"],
        trello_list=None,
        trello_board="https://trello.com/b/board1",
        trello_list_name="Ready",
        trello_label=None,
        trello_include_closed=False,
    )
    query = TrelloSource.build_query(args)
    assert query.container.endswith("board1")
    assert query.container_type == "board"
    assert query.filters["list_name"] == "Ready"
    assert query.filters["label"] == "Story"


def test_parse_arguments_file_source():
    args = parse_arguments(["tests/data/story1.md"])
    assert args.source == "file"
    assert args.story_file == "tests/data/story1.md"


def test_parse_arguments_infers_trello_from_flags():
    args = parse_arguments(["--trello-board", "https://trello.com/b/board1"])
    assert args.source == "trello"
    assert args.trello_custom_fields is False


def test_parse_arguments_trello_custom_fields():
    args = parse_arguments(
        ["--trello-board", "https://trello.com/b/board1", "--trello-custom-fields"]
    )
    assert args.source == "trello"
    assert args.trello_custom_fields is True


def test_parse_arguments_requires_a_target():
    with pytest.raises(SystemExit):
        parse_arguments([])


def test_story_input_service_single_and_batch():
    class FakeCalculator:
        def calculate_bcp(self, content):
            return {"story_name": content.strip(), "total_bcp": 3, "breakdown": {}, "steps": {}}

    registry = SourceRegistry()
    registry.register(FakeSource)
    stories = [
        Story(id="1", title="One", content="One", source="fake"),
        Story(id="2", title="Two", content="Two", source="fake"),
    ]
    service = StoryInputService(logger=logging.getLogger("test"), registry=registry)
    loaded = service.load_stories("fake", SourceQuery(container="all"), stories=stories)
    result = service.calculate(FakeCalculator(), loaded)
    assert result["count"] == 2
    assert result["results"][0]["source"]["id"] == "1"

    single = service.calculate(FakeCalculator(), loaded[:1])
    assert single["total_bcp"] == 3
    assert single["source"]["title"] == "One"


def test_format_results_json_includes_source():
    out = format_results_json({
        "story_name": "Story",
        "total_bcp": 5,
        "breakdown": {"Business Rules": 2},
        "steps": {},
        "source": {"type": "trello", "id": "card1"},
    })
    assert '"type": "trello"' in out
    assert '"id": "card1"' in out


def test_format_bcp_comment_includes_scores():
    comment = format_bcp_comment({
        "total_bcp": 13,
        "breakdown": {"Business Rules": 5, "UI Elements": 3},
        "steps": {
            "Story Maturity Complexity": {"score": 2, "classification": "Parcial"},
            "Story INVEST Maturity": {"score": 2, "classification": "Parcial"},
        },
    })
    assert "**Total BCP:** 13" in comment
    assert "Business Rules: 5" in comment
    assert "**Maturidade:** 2 (Parcial)" in comment
    assert "**INVEST:** 2 (Parcial)" in comment


def test_strip_bcp_description_removes_injected_block():
    with_block = strip_bcp_description(
        "Historia original\n\n<!-- bcp-calculator:start -->\n**Total BCP:** 5\n<!-- bcp-calculator:end -->\n"
    )
    assert "Total BCP" not in with_block
    assert "Historia original" in with_block
    assert strip_bcp_description("so a historia") == "so a historia"


def test_card_to_story_markdown_keeps_story_description_clean():
    markdown = card_to_story_markdown(
        {
            **CARD_PAYLOAD,
            "desc": (
                "Eu, ENQUANTO cliente, DESEJO pagar.\n\n"
                "<!-- bcp-calculator:start -->\n**Total BCP:** 5\n<!-- bcp-calculator:end -->\n"
            ),
            "customFieldItems": [
                {"idCustomField": "cf1", "value": {"text": "Alta"}},
                {"idCustomField": "cf-bcp", "value": {"number": "8"}},
            ],
        },
        custom_field_defs={
            "cf1": {"name": "Prioridade", "type": "text"},
            "cf-bcp": {"name": "BCP", "type": "number"},
        },
    )
    assert "Eu, ENQUANTO cliente, DESEJO pagar." in markdown
    assert "Total BCP" not in markdown
    assert "- Prioridade: Alta" in markdown
    assert "BCP:" not in markdown


def test_trello_enrich_posts_comment(requests_mock, monkeypatch):
    monkeypatch.setenv("TRELLO_API_KEY", "key")
    monkeypatch.setenv("TRELLO_TOKEN", "token")
    requests_mock.get(
        re.compile(r"https://api\.trello\.com/1/cards/card1(\?|$)"),
        json={"desc": ""},
    )
    requests_mock.post(
        re.compile(r"https://api\.trello\.com/1/cards/card1/actions/comments"),
        json={"id": "comment1"},
    )

    story = Story(
        id="card1",
        title="Card",
        content="# Card",
        source="trello",
        metadata={"board_id": "board1", "card_id": "card1"},
    )
    summary = TrelloSource.from_config().enrich(
        story,
        {
            "total_bcp": 8,
            "breakdown": {"Business Rules": 8},
            "steps": {
                "Story Maturity Complexity": {"score": 2},
                "Story INVEST Maturity": {"score": 3},
            },
        },
    )
    assert summary["comment"] is True
    assert summary["custom_fields"] == []
    assert any(call.method == "POST" and "actions/comments" in call.url for call in requests_mock.request_history)
    assert not any("customField" in call.url or call.url.rstrip("/").endswith("/customFields") for call in requests_mock.request_history)
    assert not any(
        call.method == "PUT" and "/customField/" not in call.url and "/cards/card1" in call.url
        for call in requests_mock.request_history
    )


def test_trello_enrich_strips_bcp_block_from_description(requests_mock, monkeypatch):
    monkeypatch.setenv("TRELLO_API_KEY", "key")
    monkeypatch.setenv("TRELLO_TOKEN", "token")
    requests_mock.get(
        re.compile(r"https://api\.trello\.com/1/cards/card1(\?|$)"),
        json={
            "desc": (
                "Historia original\n\n"
                "<!-- bcp-calculator:start -->\n**Total BCP:** 5\n<!-- bcp-calculator:end -->\n"
            )
        },
    )
    requests_mock.put(
        re.compile(r"https://api\.trello\.com/1/cards/card1(\?|$)"),
        json={"id": "card1", "desc": "Historia original"},
    )
    requests_mock.post(
        re.compile(r"https://api\.trello\.com/1/cards/card1/actions/comments"),
        json={"id": "comment1"},
    )
    requests_mock.get(
        re.compile(r"https://api\.trello\.com/1/boards/board1/customFields"),
        json=[
            {"id": "cf-bcp", "name": "BCP", "type": "number"},
            {"id": "cf-mat", "name": "Maturidade", "type": "number"},
            {"id": "cf-inv", "name": "INVEST", "type": "number"},
        ],
    )
    requests_mock.put(
        re.compile(r"https://api\.trello\.com/1/cards/card1/customField/.+/item"),
        json={},
    )

    story = Story(
        id="card1",
        title="Card",
        content="# Card",
        source="trello",
        metadata={"board_id": "board1", "card_id": "card1"},
    )
    TrelloSource.from_config().enrich(story, {"total_bcp": 5, "breakdown": {}, "steps": {}})

    desc_updates = [
        call
        for call in requests_mock.request_history
        if call.method == "PUT" and "/customField/" not in call.url and "/cards/card1" in call.url
    ]
    assert len(desc_updates) == 1
    assert "Historia" in desc_updates[0].text
    assert "bcp-calculator" not in desc_updates[0].text
    assert "Total" not in desc_updates[0].text


def test_trello_enrich_creates_missing_custom_fields(requests_mock, monkeypatch):
    monkeypatch.setenv("TRELLO_API_KEY", "key")
    monkeypatch.setenv("TRELLO_TOKEN", "token")
    requests_mock.get(
        re.compile(r"https://api\.trello\.com/1/cards/card1(\?|$)"),
        json={"desc": "Historia original"},
    )
    requests_mock.post(
        re.compile(r"https://api\.trello\.com/1/cards/card1/actions/comments"),
        json={"id": "comment1"},
    )
    requests_mock.get(
        re.compile(r"https://api\.trello\.com/1/boards/board1/customFields"),
        json=[],
    )

    def _created_field(request, context):
        import json as json_lib

        body = json_lib.loads(request.body)
        return {"id": f"cf-{body['name'].lower()}", "name": body["name"], "type": body["type"]}

    requests_mock.post(
        re.compile(r"https://api\.trello\.com/1/customFields"),
        json=_created_field,
    )
    requests_mock.put(
        re.compile(r"https://api\.trello\.com/1/cards/card1/customField/.+/item"),
        json={},
    )

    story = Story(
        id="card1",
        title="Card",
        content="# Card",
        source="trello",
        metadata={"board_id": "board1", "card_id": "card1"},
    )
    summary = TrelloSource.from_config(write_custom_fields=True).enrich(
        story,
        {
            "total_bcp": 5,
            "breakdown": {},
            "steps": {
                "Story Maturity Complexity": {"score": 2},
                "Story INVEST Maturity": {"score": 2},
            },
        },
    )
    created = [
        call
        for call in requests_mock.request_history
        if call.method == "POST" and "/customFields" in call.url
    ]
    assert len(created) == 3
    assert summary["custom_fields"] == ["BCP", "Maturidade", "INVEST"]


def test_write_back_calls_enrich():
    class FakeCalculator:
        def calculate_bcp(self, content):
            return {"story_name": "S", "total_bcp": 4, "breakdown": {}, "steps": {}}

    class WritingSource(FakeSource):
        def enrich(self, story, results):
            return {"comment": True}

    registry = SourceRegistry()
    registry.register(WritingSource)
    service = StoryInputService(logger=logging.getLogger("test"), registry=registry)
    story = Story(id="1", title="One", content="One", source="fake")
    result = service.calculate(
        FakeCalculator(),
        [story],
        source=WritingSource(stories=[story]),
        write_back=True,
    )
    assert result["write_back"]["comment"] is True
