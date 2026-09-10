from typing import Any
import httpx
from mcp.server.fastmcp import FastMCP
import uuid
import logging

from src.bcp.bcp_calculator import BCPCalculator
from src.bcp.logger import setup_logger
from src.bcp.sources import SourceQuery, StoryInputService

# Initialize FastMCP server
mcp = FastMCP("bcp-calculator-mcp")

logger = setup_logger(logging.INFO)

@mcp.tool()
async def calculate_bcp(story_content: str, provider: str = "openai") -> dict:
    """Calculate BCP.

    Args:
        story: User story content
        provider: LLM provider to use (openai or claude)
    """
    """Start BCP calculation job."""
    calculator = BCPCalculator(logger, provider_name=provider)
    result = calculator.calculate_bcp(story_content)

    return {"result": result}


@mcp.tool()
async def calculate_bcp_from_source(
    source: str,
    id: str = None,
    container: str = None,
    container_type: str = None,
    provider: str = "openai",
    write_back: bool = True,
    write_custom_fields: bool = False,
) -> dict:
    """Calculate BCP from a registered story source (file, trello, ...).

    Args:
        source: Source name (file, trello)
        id: Single story identifier (file path, Trello card URL, issue key, ...)
        container: Collection identifier (directory, board, list, project, ...)
        container_type: Type of container (board, list, directory, ...)
        provider: LLM provider to use (openai or claude)
        write_back: Write a BCP comment back to the source (Trello)
        write_custom_fields: Also create/update Trello custom fields (Premium)
    """
    calculator = BCPCalculator(logger, provider_name=provider)
    service = StoryInputService(logger=logger)
    result = service.process(
        source,
        SourceQuery(item=id, container=container, container_type=container_type),
        calculator,
        write_back=write_back,
        write_custom_fields=write_custom_fields,
    )
    return {"result": result}


if __name__ == "__main__":
    logger.info(f"MCP Server starting...")
    mcp.run(transport='stdio')
