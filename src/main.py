#!/usr/bin/env python3
"""
BCP Calculator - Command Line Interface

This script provides a CLI for calculating Business Complexity Points (BCP)
of user stories using a series of predefined prompts and multiple LLM providers.
"""

import argparse
import json
import logging
import sys
from typing import Any, Dict
from dotenv import load_dotenv

from bcp import BCPCalculator, setup_logger
from bcp.sources import (
    SourceConfigError,
    SourceError,
    StoryInputService,
    get_registry,
)


def parse_arguments(argv=None):
    """Parse command line arguments."""
    registry = get_registry()
    available_sources = ", ".join(registry.names())

    parser = argparse.ArgumentParser(
        description="Calculate Business Complexity Points (BCP) for a user story."
    )
    parser.add_argument(
        "story_file",
        nargs="?",
        type=str,
        help="Path to a user story file, or a source-specific id/URL when using --source",
    )
    parser.add_argument(
        "--source",
        type=str,
        choices=registry.names(),
        default="file",
        help=f"Story input source (default: file). Available: {available_sources}",
    )
    parser.add_argument(
        "--id",
        dest="source_id",
        help="Story identifier in the selected source (file path, Trello card URL, issue key, ...)",
    )
    parser.add_argument(
        "--container",
        help="Collection identifier in the selected source (directory, board, list, project, ...)",
    )
    parser.add_argument(
        "--container-type",
        help="Type of --container when the source supports more than one (board, list, directory, ...)",
    )
    parser.add_argument(
        "--filter",
        action="append",
        dest="source_filters",
        default=[],
        metavar="KEY=VALUE",
        help="Source-specific filter (repeatable). Example: --filter label=Story",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set the logging level (default: INFO)",
    )
    parser.add_argument(
        "--output-file",
        type=str,
        help="Path to save the output results (default: print to stdout)",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["text", "json"],
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--provider",
        type=str,
        choices=["openai", "claude", "flow-openai", "flow-bedrock"],
        default="openai",
        help="LLM provider to use (default: openai)",
    )
    parser.add_argument(
        "--no-write-back",
        action="store_true",
        help="Do not write BCP results back to the source (Trello comment)",
    )

    registry.configure_cli(parser)
    args = parser.parse_args(argv)

    try:
        args.source = registry.infer_source_name(args, default="file")
        registry.get(args.source).build_query(args)
    except SourceConfigError as exc:
        parser.error(str(exc))

    return args


def load_stories_from_args(args, logger: logging.Logger):
    """Resolve CLI arguments into normalized stories via the source registry."""
    registry = get_registry()
    source_cls = registry.get(args.source)
    query = source_cls.build_query(args)
    service = StoryInputService(logger=logger)
    return service.load_stories(args.source, query)


def save_or_print_results(results: Dict[str, Any], output_format: str, output_file: str = None, logger: logging.Logger = None) -> None:
    """Save results to file or print to stdout."""
    formatted_results = format_results_json(results) if output_format == "json" else format_results_text(results)

    if output_file:
        try:
            with open(output_file, 'w', encoding='utf-8') as file:
                file.write(formatted_results)
            if logger:
                logger.info(f"Results saved to {output_file}")
        except Exception as e:
            if logger:
                logger.error(f"Error saving results to {output_file}: {str(e)}")
            sys.exit(1)
    else:
        print(formatted_results)


def main():
    """Main entry point for the BCP Calculator CLI."""
    load_dotenv()
    args = parse_arguments()

    log_level = getattr(logging, args.log_level)
    logger = setup_logger(log_level)

    try:
        registry = get_registry()
        source_cls = registry.get(args.source)
        query = source_cls.build_query(args)
        calculator = BCPCalculator(logger, provider_name=args.provider)
        results = StoryInputService(logger=logger).process(
            args.source,
            query,
            calculator,
            write_back=not args.no_write_back,
            write_custom_fields=getattr(args, "trello_custom_fields", False),
        )
    except SourceError as exc:
        logger.error(str(exc))
        sys.exit(1)
    except Exception as exc:
        logger.error(f"Error calculating BCP: {str(exc)}")
        sys.exit(1)

    save_or_print_results(results, args.format, args.output_file, logger)
    print_write_back_status(results, logger)


def print_write_back_status(results: Dict[str, Any], logger: logging.Logger) -> None:
    """Repeat write-back outcome on the same logger used by the calculation steps."""
    items = results.get("results") if isinstance(results.get("results"), list) and "count" in results else [results]
    for item in items:
        source = item.get("source") or {}
        title = source.get("title") or source.get("card_name") or item.get("story_name") or "unknown"
        url = source.get("url") or source.get("card_url") or source.get("id") or ""
        write_back = item.get("write_back")
        if not write_back or write_back.get("skipped"):
            reason = (write_back or {}).get("reason") or "not attempted"
            logger.warning(f"[Write-back] SKIPPED '{title}' {url}: {reason}")
            continue
        if write_back.get("error") or write_back.get("ok") is False:
            logger.error(
                f"[Write-back] FAILED '{title}' {url}: {write_back.get('error') or 'unknown error'}"
            )
            continue
        fields = write_back.get("custom_fields") or []
        logger.info(
            f"[Write-back] SUCCESS '{title}' {url} "
            f"comment={'yes' if write_back.get('comment') else 'no'} "
            f"custom_fields={','.join(fields) if fields else 'none'}"
        )


def results_as_dict(results: Dict[str, Any]) -> Dict[str, Any]:
    """Convert calculator output into the public JSON structure."""
    if "results" in results and "count" in results:
        serialized = []
        for item in results["results"]:
            if "error" in item and "steps" not in item:
                serialized.append(item)
            else:
                serialized.append(_single_result_as_dict(item))
        return {
            "source": results.get("source"),
            "count": results["count"],
            "results": serialized,
        }
    return _single_result_as_dict(results)


def _single_result_as_dict(results: Dict[str, Any]) -> Dict[str, Any]:
    json_output = {
        "story_name": results.get("story_name", "Unknown"),
        "total_bcp": results.get("total_bcp", 0),
        "components": results.get("breakdown", {}),
        "steps": {},
    }

    maturity_score = 0
    invest_score = 0

    for step_name, step_result in (results.get("steps") or {}).items():
        if isinstance(step_result, dict):
            step_data = {
                "assessment": step_result.get("assessment", step_result.get("description", "")),
                "score": step_result.get("score", step_result.get("total", 0)),
                "classification": step_result.get("classification", ""),
                "raw_response": step_result.get("raw_response", ""),
            }
            json_output["steps"][step_name] = step_data

            if step_name == "Story Maturity Complexity":
                maturity_score = step_result.get("score", 0)
            elif step_name == "Story INVEST Maturity":
                invest_score = step_result.get("score", 0)
        else:
            json_output["steps"][step_name] = {"raw_response": str(step_result)}

    json_output["score"] = {
        "maturity": maturity_score,
        "invest": invest_score,
    }

    if results.get("source"):
        json_output["source"] = results["source"]
    if results.get("write_back"):
        json_output["write_back"] = results["write_back"]
    if results.get("error"):
        json_output["error"] = results["error"]

    return json_output


def format_results_json(results: Dict[str, Any]) -> str:
    """Format the results as JSON."""
    return json.dumps(results_as_dict(results), indent=2, ensure_ascii=False)


def format_results_text(results: Dict[str, Any]) -> str:
    """Format the results as text (legacy format)."""
    if "results" in results and "count" in results:
        chunks = []
        for index, item in enumerate(results["results"], 1):
            title = (
                (item.get("source") or {}).get("title")
                or item.get("story_name")
                or f"Story {index}"
            )
            chunks.append(f"######## {title} ########")
            if "error" in item and "steps" not in item:
                chunks.append(f"Error: {item['error']}")
            else:
                chunks.append(format_results_text(item))
        return "\n\n".join(chunks)

    output = []

    if results.get("source"):
        source = results["source"]
        output.append(f"=== SOURCE ({source.get('type', 'unknown')}) ===")
        if source.get("title"):
            output.append(f"Title: {source['title']}")
        if source.get("id"):
            output.append(f"Id: {source['id']}")
        if source.get("url"):
            output.append(f"URL: {source['url']}")
        output.append("")

    for step_name, step_result in (results.get("steps") or {}).items():
        output.append(f"=== {step_name} ===")
        output.append(str(step_result))
        output.append("")

    output.append("=== FINAL BUSINESS COMPLEXITY POINTS ===")
    output.append(f"Total BCP: {results.get('total_bcp', 0)}")
    output.append("")

    output.append("=== BCP BREAKDOWN ===")
    for component, score in (results.get("breakdown") or {}).items():
        output.append(f"{component}: {score}")

    return "\n".join(output)


if __name__ == "__main__":
    main()
