"""
Pydantic models for the BCP Calculator API.
"""

from pydantic import BaseModel, Field
from typing import Dict, Any, Optional


class StoryRequest(BaseModel):
    """Request model for BCP calculation."""
    content: str = Field(..., description="User story content")
    provider: str = Field("openai", description="LLM provider to use (openai or claude)")


class SourceStoryRequest(BaseModel):
    """Request model for BCP calculation from a pluggable story source."""
    source: str = Field(..., description="Story source name (file, trello, ...)")
    id: Optional[str] = Field(
        None,
        description="Story identifier (file path, Trello card URL, issue key, ...)",
    )
    container: Optional[str] = Field(
        None,
        description="Collection identifier (directory, board, list, project, ...)",
    )
    container_type: Optional[str] = Field(
        None,
        description="Type of container when the source supports more than one (board, list, directory, ...)",
    )
    filters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Source-specific filters (for Trello: list_name, label, include_closed)",
    )
    provider: str = Field("openai", description="LLM provider to use (openai or claude)")
    write_back: bool = Field(
        True,
        description="Write BCP results back to the source (Trello comment by default)",
    )
    write_custom_fields: bool = Field(
        False,
        description="Create/update Trello custom fields BCP, Maturidade, and INVEST (requires Trello Premium)",
    )


class JobStatus(BaseModel):
    """Response model for job status."""
    job_id: str = Field(..., description="Unique identifier for the job")
    status: str = Field(..., description="Current status of the job (pending, processing, completed, failed)")
    result: Optional[Dict[str, Any]] = Field(None, description="Results of the BCP calculation if completed")
    error: Optional[str] = Field(None, description="Error message if job failed")