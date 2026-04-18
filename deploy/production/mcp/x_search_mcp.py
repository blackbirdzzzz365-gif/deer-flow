#!/usr/bin/env python3
from __future__ import annotations

import os
from datetime import date
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

DEFAULT_BASE_URL = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-4-1-fast-non-reasoning"
DEFAULT_MAX_TURNS = 2
DEFAULT_TIMEOUT_SECONDS = 30


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _env_int(name: str, default: int) -> int:
    value = _env(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _normalize_handles(handles: list[str] | None) -> list[str]:
    if not handles:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_handle in handles:
        handle = raw_handle.strip()
        if not handle:
            continue
        handle = handle.removeprefix("@")
        key = handle.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(handle)
    return normalized


def _validate_iso_date(name: str, value: str | None) -> None:
    if not value:
        return
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must use YYYY-MM-DD format") from exc


def _extract_annotation_urls(annotations: list[dict[str, Any]]) -> list[str]:
    citations: list[str] = []
    seen: set[str] = set()
    for annotation in annotations:
        url = annotation.get("url")
        if annotation.get("type") != "url_citation" or not isinstance(url, str) or not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        citations.append(url)
    return citations


def _extract_text_and_citations(data: dict[str, Any]) -> tuple[str, list[str]]:
    for output in data.get("output", []):
        if output.get("type") == "message":
            for block in output.get("content", []):
                if block.get("type") == "output_text" and isinstance(block.get("text"), str) and block["text"]:
                    return block["text"], _extract_annotation_urls(block.get("annotations", []))
        if output.get("type") == "output_text" and isinstance(output.get("text"), str) and output["text"]:
            return output["text"], _extract_annotation_urls(output.get("annotations", []))

    fallback = data.get("output_text")
    if isinstance(fallback, str) and fallback:
        return fallback, []
    return "No response", []


def _extract_inline_citations(data: dict[str, Any], enabled: bool) -> list[Any] | None:
    if not enabled:
        return None
    inline_citations = data.get("inline_citations")
    return inline_citations if isinstance(inline_citations, list) and inline_citations else None


def _build_request_body(
    *,
    query: str,
    model: str,
    max_turns: int,
    allowed_x_handles: list[str],
    excluded_x_handles: list[str],
    from_date: str | None,
    to_date: str | None,
    enable_image_understanding: bool,
    enable_video_understanding: bool,
) -> dict[str, Any]:
    tool_payload: dict[str, Any] = {"type": "x_search"}
    if allowed_x_handles:
        tool_payload["allowed_x_handles"] = allowed_x_handles
    if excluded_x_handles:
        tool_payload["excluded_x_handles"] = excluded_x_handles
    if from_date:
        tool_payload["from_date"] = from_date
    if to_date:
        tool_payload["to_date"] = to_date
    if enable_image_understanding:
        tool_payload["enable_image_understanding"] = True
    if enable_video_understanding:
        tool_payload["enable_video_understanding"] = True

    return {
        "model": model,
        "input": [{"role": "user", "content": query}],
        "tools": [tool_payload],
        "max_turns": max_turns,
    }


server = FastMCP(
    name="x-search",
    instructions="Search X (formerly Twitter) using xAI and return concise results with citations.",
    log_level=_env("X_SEARCH_MCP_LOG_LEVEL", "INFO") or "INFO",
)


@server.tool(
    name="x_search",
    description=(
        "Search X (formerly Twitter) using xAI, including targeted post or thread lookups. "
        "For per-post stats like reposts, replies, bookmarks, or views, prefer the exact post URL or status ID."
    ),
)
async def x_search(
    query: str,
    allowed_x_handles: list[str] | None = None,
    excluded_x_handles: list[str] | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    enable_image_understanding: bool = False,
    enable_video_understanding: bool = False,
) -> dict[str, Any]:
    api_key = _env("XAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing XAI_API_KEY for x_search MCP server.")

    _validate_iso_date("from_date", from_date)
    _validate_iso_date("to_date", to_date)

    model = _env("XAI_X_SEARCH_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL
    base_url = (_env("XAI_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL).rstrip("/")
    max_turns = _env_int("XAI_X_SEARCH_MAX_TURNS", DEFAULT_MAX_TURNS)
    timeout_seconds = _env_int("XAI_X_SEARCH_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
    inline_citations_enabled = _env_bool("XAI_X_SEARCH_INLINE_CITATIONS", False)

    allowed_handles = _normalize_handles(allowed_x_handles)
    excluded_handles = _normalize_handles(excluded_x_handles)

    request_body = _build_request_body(
        query=query,
        model=model,
        max_turns=max_turns,
        allowed_x_handles=allowed_handles,
        excluded_x_handles=excluded_handles,
        from_date=from_date,
        to_date=to_date,
        enable_image_understanding=enable_image_understanding,
        enable_video_understanding=enable_video_understanding,
    )

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            f"{base_url}/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body_preview = exc.response.text[:500]
            raise RuntimeError(f"xAI x_search request failed with {exc.response.status_code}: {body_preview}") from exc
        data = response.json()

    content, annotation_citations = _extract_text_and_citations(data)
    citations = data.get("citations")
    if not isinstance(citations, list) or not citations:
        citations = annotation_citations

    result: dict[str, Any] = {
        "query": query,
        "provider": "xai",
        "model": model,
        "content": content,
        "citations": citations,
    }
    inline_citations = _extract_inline_citations(data, inline_citations_enabled)
    if inline_citations is not None:
        result["inline_citations"] = inline_citations

    applied_filters: dict[str, Any] = {}
    if allowed_handles:
        applied_filters["allowed_x_handles"] = allowed_handles
    if excluded_handles:
        applied_filters["excluded_x_handles"] = excluded_handles
    if from_date:
        applied_filters["from_date"] = from_date
    if to_date:
        applied_filters["to_date"] = to_date
    if enable_image_understanding:
        applied_filters["enable_image_understanding"] = True
    if enable_video_understanding:
        applied_filters["enable_video_understanding"] = True
    if applied_filters:
        result["filters"] = applied_filters

    response_id = data.get("id")
    if isinstance(response_id, str) and response_id:
        result["response_id"] = response_id

    return result


if __name__ == "__main__":
    server.run(transport="stdio")
