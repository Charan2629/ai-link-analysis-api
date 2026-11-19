import time
from typing import Optional
from cachetools import TTLCache

from app.config import get_settings
from app.schemas import (
    AnalysisMetadata,
    AnalysisResult,
    BrandInfo,
    LinkAnalysisResponse,
)
from app.services.competitor_service import (
    enrich_and_validate_competitors,
    find_explicit_competitor_mentions,
)
from app.services.llm_service import analyze_website_with_llm
from app.services.website_extractor import fetch_and_extract_website
from app.utils.validators import validate_and_sanitize_url

# In-memory TTL cache: max 1000 URLs, 1 hour (3600s) default TTL
_settings = get_settings()
analysis_cache: TTLCache = TTLCache(
    maxsize=_settings.CACHE_MAXSIZE,
    ttl=_settings.CACHE_TTL_SECONDS,
)


def get_cached_analysis(normalized_url: str) -> Optional[LinkAnalysisResponse]:
    """Retrieve cached analysis if present and not expired."""
    return analysis_cache.get(normalized_url)


def set_cached_analysis(normalized_url: str, response: LinkAnalysisResponse) -> None:
    """Store analysis result in TTL cache."""
    analysis_cache[normalized_url] = response


async def analyze_url_pipeline(raw_url: str) -> LinkAnalysisResponse:
    """
    Execute complete end-to-end link analysis workflow:
    1. Sanitize & validate URL (with SSRF DNS checking)
    2. Check in-memory TTLCache for duplicate requests
    3. Asynchronously fetch HTML & clean textual content
    4. Detect competitor hints and build context
    5. Call Gemini LLM (gemini-3.5-flash-lite) with retry
    6. Validate and enrich competitor models
    7. Measure latency, construct response, and cache
    """
    start_time = time.perf_counter()

    # 1. URL validation & SSRF protection
    normalized_url = validate_and_sanitize_url(raw_url)

    # 2. Cache check
    cached = get_cached_analysis(normalized_url)
    if cached is not None:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        # Return a copy marked as cached
        return LinkAnalysisResponse(
            success=cached.success,
            website=cached.website,
            brand=cached.brand,
            analysis=cached.analysis,
            metadata=AnalysisMetadata(
                model=cached.metadata.model,
                processing_time_ms=round(elapsed_ms, 2),
                cached=True,
                token_usage=cached.metadata.token_usage,
            ),
        )

    # 3. Fetch and clean website content
    extracted = await fetch_and_extract_website(normalized_url)

    # 4. Search for competitor mentions in page
    competitor_hints = find_explicit_competitor_mentions(extracted.cleaned_body_text)

    # 5. Send to LLM
    context_text = extracted.to_llm_context()
    brand, analysis_result, model_used, token_usage = await analyze_website_with_llm(
        website_context=context_text,
        competitor_hints=competitor_hints,
    )

    # 6. Enrich competitor sources (extracted vs ai_inferred)
    enriched_competitors = enrich_and_validate_competitors(
        competitors=analysis_result.competitor_analysis.competitors,
        page_text=extracted.cleaned_body_text,
    )
    analysis_result.competitor_analysis.competitors = enriched_competitors

    elapsed_ms = (time.perf_counter() - start_time) * 1000

    response = LinkAnalysisResponse(
        success=True,
        website=normalized_url,
        brand=brand,
        analysis=analysis_result,
        metadata=AnalysisMetadata(
            model=model_used,
            processing_time_ms=round(elapsed_ms, 2),
            cached=False,
            token_usage=token_usage,
        ),
    )

    # 7. Store in cache
    set_cached_analysis(normalized_url, response)

    return response
