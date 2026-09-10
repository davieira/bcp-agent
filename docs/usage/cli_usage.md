# CLI Usage Guide for BCP Calculator

This guide explains how to use the BCP Calculator as a command-line tool.

## Prerequisites

Before using the CLI, make sure you have:

1. Installed all dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set up your environment variables:
   ```bash
   cp .env.example .env
   ```
   Then edit the `.env` file to add your API keys for the providers you want to use (OpenAI and/or Anthropic).

## Basic Usage

The basic syntax for using the BCP Calculator CLI is:

```bash
python run_cli.py <story_file> [OPTIONS]
python run_cli.py --source trello --id <card-url> [OPTIONS]
```

Where:
- `<story_file>` is the path to the markdown file containing your user story (default source: `file`)

Stories can also be loaded from a registered input source such as Trello. See [Story Input Sources](story_sources.md).

## Options

The CLI supports the following options:

| Option | Description | Default |
|--------|-------------|---------|
| `--source` | Story input source (`file`, `trello`) | file |
| `--id` | Story identifier in the selected source (file path, Trello card URL, ...) | None |
| `--container` | Collection identifier (directory, board, list, ...) | None |
| `--container-type` | Type of `--container` (`board`, `list`, `directory`, ...) | None |
| `--filter KEY=VALUE` | Source-specific filter (repeatable) | None |
| `--trello-list` | Trello list id (implies `--source trello`) | None |
| `--trello-board` | Trello board id or URL (implies `--source trello`) | None |
| `--trello-list-name` | Filter board cards by list name | None |
| `--trello-label` | Filter Trello cards by label name | None |
| `--trello-include-closed` | Include archived Trello cards | False |
| `--trello-custom-fields` | Create/update Trello custom fields `BCP`, `Maturidade`, `INVEST` (Premium) | off (comment only) |
| `--no-write-back` | Do not write BCP results back to Trello cards | write-back on (comment) |
| `--log-level` | Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) | INFO |
| `--output-file` | Path to save the output results | None (print to stdout) |
| `--provider` | LLM provider to use (openai or claude) | openai |
| `--format` | Output format (text or json) | json |

## Examples

### Basic Example

Process a user story with the default provider (OpenAI):

```bash
python run_cli.py tests/data/story1.md
```

### Trello

```bash
python run_cli.py --source trello --id https://trello.com/c/abc123
python run_cli.py --trello-list LIST_ID --provider openai
python run_cli.py --trello-board https://trello.com/b/shortLink --trello-list-name "Ready"
python run_cli.py --trello-board https://trello.com/b/shortLink --trello-custom-fields
```

Trello credentials (`TRELLO_API_KEY` and `TRELLO_TOKEN`) must be set in `.env`.

### Using Different Providers

Process with OpenAI (explicitly):

```bash
python run_cli.py tests/data/story1.md --provider openai
```

Process with Claude:

```bash
python run_cli.py tests/data/story1.md --provider claude
```

### Saving Results

Save the results to a JSON file:

```bash
python run_cli.py tests/data/story1.md --output-file results.json
```

Save results in text format:

```bash
python run_cli.py tests/data/story1.md --format text --output-file results.txt
```

### Detailed Logging

Run with detailed debug logs:

```bash
python run_cli.py tests/data/story1.md --log-level DEBUG
```

### Complete Example

Process a story with Claude, save as text with detailed logs:

```bash
python run_cli.py tests/data/story1.md --provider claude --format text --output-file claude_results.txt --log-level DEBUG
```

## Understanding the Output

The output includes:

- Results from each step in the process
- Final Business Complexity Points (BCP)
- Breakdown of points by component:
  - Business Rules
  - Interface Elements
  - External Integrations (Boundaries)

### Sample JSON Output

```json
{
  "story_name": "User Story: Add Payment Method",
  "total_bcp": 13,
  "components": {
    "Business Rules": 5,
    "UI Elements": 3,
    "External Integrations": 5
  },
  "steps": {
    "Story Maturity Complexity": {
      "assessment": "The story is well-defined with clear acceptance criteria",
      "score": 4,
      "classification": "Mature"
    },
    "Story INVEST Maturity": {
      "assessment": "Independent, testable, but somewhat large in scope",
      "score": 3,
      "classification": "Partially Mature"
    },
    "Business Rules Complexity": {
      "total": 5
    },
    "UI Elements Complexity": {
      "total": 3
    },
    "External Integrations Complexity": {
      "total": 5
    }
  }
}
```

### Sample Text Output

```
=== Story Maturity Complexity ===
The story is well-defined with clear acceptance criteria
Score: 4
Classification: Mature

=== Story INVEST Maturity ===
Independent, testable, but somewhat large in scope
Score: 3
Classification: Partially Mature

=== Business Rules Complexity ===
Total: 5

=== UI Elements Complexity ===
Total: 3

=== External Integrations Complexity ===
Total: 5

=== FINAL BUSINESS COMPLEXITY POINTS ===
Total BCP: 13

=== BCP BREAKDOWN ===
Business Rules: 5
UI Elements: 3
External Integrations: 5
```

## Troubleshooting

### Common Issues

1. **API Key Issues**:
   - Ensure the appropriate API keys are properly set in `.env`
   - Check that you have access to the LLM provider you're trying to use

2. **File Path Errors**:
   - Use absolute paths if experiencing issues with relative paths
   - Ensure the story file exists and has the correct permissions
   - For Trello, set `TRELLO_API_KEY` and `TRELLO_TOKEN` and pass a card, list, or board

3. **Provider Issues**:
   - If a provider is not working, try switching to a different provider
   - Check the API key and network connection