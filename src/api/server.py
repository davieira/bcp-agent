"""
FastAPI server for the BCP Calculator API.
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from typing import Dict, Any
import logging
import uuid

from .models import StoryRequest, SourceStoryRequest, JobStatus
from ..bcp import BCPCalculator, setup_logger
from ..bcp.sources import (
    SourceAuthError,
    SourceConfigError,
    SourceError,
    SourceNotFoundError,
    SourceQuery,
    StoryInputService,
    get_registry,
)

# In-memory job storage (replace with database for production)
jobs = {}

app = FastAPI(
    title="BCP Calculator API",
    description="API for calculating Business Complexity Points (BCP) of user stories",
    version="1.0.0"
)


@app.get("/")
def read_root():
    """Root endpoint returning API information."""
    return {
        "name": "BCP Calculator API",
        "version": "1.0.0",
        "description": "API for calculating Business Complexity Points (BCP) of user stories"
    }


@app.get("/sources")
def list_sources():
    """List registered story input sources."""
    registry = get_registry()
    return {
        "sources": [
            {
                "name": source_cls.name,
                "description": source_cls.description,
                "required_env_vars": list(source_cls.required_env_vars),
            }
            for source_cls in registry.classes()
        ]
    }


@app.post("/calculate", response_model=Dict[str, str])
def calculate_bcp(story: StoryRequest, background_tasks: BackgroundTasks):
    """Start BCP calculation job from inline story content."""
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending", "result": None}

    background_tasks.add_task(
        process_bcp_calculation,
        job_id=job_id,
        story_content=story.content,
        provider=story.provider
    )

    return {"job_id": job_id}


@app.post("/calculate/source", response_model=Dict[str, str])
def calculate_bcp_from_source(request: SourceStoryRequest, background_tasks: BackgroundTasks):
    """Start BCP calculation job from a registered story source (file, trello, ...)."""
    registry = get_registry()
    try:
        registry.get(request.source)
    except SourceConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not request.id and not request.container:
        raise HTTPException(
            status_code=400,
            detail="Provide 'id' for a single story or 'container' for a collection",
        )

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending", "result": None}

    background_tasks.add_task(
        process_source_calculation,
        job_id=job_id,
        source_name=request.source,
        query=SourceQuery(
            item=request.id,
            container=request.container,
            container_type=request.container_type,
            filters=request.filters or {},
        ),
        provider=request.provider,
        write_back=request.write_back,
        write_custom_fields=request.write_custom_fields,
    )

    return {"job_id": job_id}


@app.get("/status/{job_id}", response_model=JobStatus)
def get_status(job_id: str):
    """Get job status and results if complete."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job_id,
        "status": jobs[job_id]["status"],
        "result": jobs[job_id].get("result"),
        "error": jobs[job_id].get("error")
    }


def process_bcp_calculation(job_id: str, story_content: str, provider: str):
    """Process BCP calculation in background."""
    logger = setup_logger(logging.INFO)

    try:
        jobs[job_id]["status"] = "processing"

        calculator = BCPCalculator(logger, provider_name=provider)
        result = calculator.calculate_bcp(story_content)

        jobs[job_id] = {"status": "completed", "result": result}
    except Exception as e:
        logger.error(f"Error calculating BCP: {str(e)}")
        jobs[job_id] = {"status": "failed", "error": str(e)}


def process_source_calculation(
    job_id: str,
    source_name: str,
    query: SourceQuery,
    provider: str,
    write_back: bool = True,
    write_custom_fields: bool = False,
):
    """Load stories from a source and calculate BCP in the background."""
    logger = setup_logger(logging.INFO)

    try:
        jobs[job_id]["status"] = "processing"

        service = StoryInputService(logger=logger)
        calculator = BCPCalculator(logger, provider_name=provider)
        result = service.process(
            source_name,
            query,
            calculator,
            write_back=write_back,
            write_custom_fields=write_custom_fields,
        )

        jobs[job_id] = {"status": "completed", "result": result}
    except SourceAuthError as e:
        logger.error(str(e))
        jobs[job_id] = {"status": "failed", "error": str(e)}
    except SourceNotFoundError as e:
        logger.error(str(e))
        jobs[job_id] = {"status": "failed", "error": str(e)}
    except SourceConfigError as e:
        logger.error(str(e))
        jobs[job_id] = {"status": "failed", "error": str(e)}
    except SourceError as e:
        logger.error(str(e))
        jobs[job_id] = {"status": "failed", "error": str(e)}
    except Exception as e:
        logger.error(f"Error calculating BCP from source: {str(e)}")
        jobs[job_id] = {"status": "failed", "error": str(e)}
