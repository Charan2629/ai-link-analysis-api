import asyncio
import json
import logging
import re
from typing import Any, Dict, Optional, Tuple
import httpx
from google import genai
from google.genai import types

from app.config import get_settings
from app.schemas import (
    AnalysisResult,
    BrandInfo,
    CompetitorAnalysis,
    CompetitorItem,
    CustomerProfileItem,
    SearchQueryItem,
    SEOImprovements,
    ServiceItem,
    SupportingContentItem,
    TargetAudience,
    TokenUsage,
)

logger = logging.getLogger(__name__)


class LLMServiceException(Exception):
    """Base exception for LLM processing failures."""
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class LLMConfigurationException(LLMServiceException):
    """Raised when API key or model configuration is missing."""
    def __init__(self, message: str = "GEMINI_API_KEY is not configured."):
        super().__init__(message, status_code=502)


def get_genai_client(api_key: Optional[str] = None) -> genai.Client:
    """Instantiate official google-genai SDK client."""
    settings = get_settings()
    key = api_key or settings.GEMINI_API_KEY
    if not key or key == "your_gemini_api_key_here":
        raise LLMConfigurationException(
            "GEMINI_API_KEY is not configured. Please add a valid Gemini API key to your .env file."
        )
    return genai.Client(api_key=key)


def build_analysis_prompt(website_context: str, competitor_hints: list[str]) -> str:
    """
    Construct high-precision prompt demanding strict JSON adhering to all 5 sections.
    Explicitly forbids inventing search volumes or ranking metrics.
    """
    hints_text = ""
    if competitor_hints:
        hints_text = f"\nExplicit competitor or comparison references detected on page: {', '.join(competitor_hints)}\n"

    prompt = f"""You are an elite Business Intelligence, Digital Marketing, and Technical SEO Analyst.
Analyze the following extracted website content and generate a comprehensive, highly accurate business and link analysis.

{website_context}
{hints_text}

MANDATORY RULES:
1. Ground your analysis strictly in the provided website content. Do not hallucinate capabilities or services the company does not offer.
2. In Section 1 (Competitors): Identify at least 3 genuine or direct market competitors. If competitors are not explicitly named in the text, infer realistic competitors based on the business category and offerings, and set "source": "ai_inferred".
3. In Section 2 (Search Queries): Generate EXACTLY 5 high-value search queries. Across the 5 queries, ensure coverage of the 5 requested platforms: "Google Search", "Facebook", "Instagram", "LinkedIn", "X (Twitter)".
   CRITICAL: DO NOT INVENT or report fake search volumes, keyword difficulties, or ranking numbers. Indicate platform, intent, business relevance, and target audience only.
4. In Section 3 (SEO Improvements): Recommend practical keywords (primary, secondary, long-tail, business), an optimized title, meta description, and supporting content assets (landing pages, FAQs, blogs).
5. In Section 4 (Top Services): Identify the top 5 core services or offerings. Mark "source" as "extracted" if directly present in the text, or "ai_inferred" if derived.
6. In Section 5 (Target Audience): Provide a detailed audience breakdown including primary/secondary audience, industries, business types, customer profiles (with audience_type, business_type, core_requirement), geographical focus, customer needs, customer interests, and recommended marketing segments.
7. Return ONLY a valid JSON object matching the exact schema specified below. Do not include markdown commentary or preamble outside the JSON.

REQUIRED JSON SCHEMA:
{{
  "brand": {{
    "name": "Brand or Company Name",
    "category": "Main Industry / Business Category",
    "summary": "Short, human-friendly summary of the business (2-3 sentences)"
  }},
  "analysis": {{
    "competitor_analysis": {{
      "brand_overview": "Detailed overview of the brand and its market stance",
      "main_business_category": "Industry category",
      "main_products_and_services": ["Service 1", "Product 2"],
      "competitors": [
        {{
          "name": "Competitor Name",
          "main_service": "Main competing service",
          "target_market": "Market segment (e.g. Enterprise, SMB)",
          "strengths": ["Strength 1", "Strength 2"],
          "weaknesses_or_gaps": ["Weakness or gap 1"],
          "source": "ai_inferred"
        }}
      ],
      "competitive_advantages": ["Advantage 1", "Advantage 2"],
      "opportunities": ["Market positioning opportunity 1"]
    }},
    "target_search_queries": [
      {{
        "query": "Target search query string",
        "platforms": ["Google Search", "LinkedIn"],
        "intent": "Service Search / B2B Search",
        "business_relevance": "Why this query matches the business",
        "target_audience": "Target persona executing this search"
      }}
    ],
    "seo_improvements": {{
      "primary_keyword": "Primary target keyword",
      "secondary_keywords": ["Keyword 1", "Keyword 2"],
      "long_tail_keywords": ["Long tail query 1", "Long tail query 2"],
      "business_keywords": ["Business keyword 1", "Business keyword 2"],
      "recommended_title": "SEO Optimized Page Title (under 60 chars)",
      "meta_description": "SEO Optimized Meta Description (150-160 chars)",
      "supporting_content": [
        {{
          "content_type": "Service Landing Page / FAQ / Blog Topic / Industry Guide",
          "title_or_topic": "Suggested Title or Topic",
          "rationale": "Why this content improves search visibility"
        }}
      ]
    }},
    "top_services": [
      {{
        "service_name": "Service Name",
        "description": "Short service explanation",
        "target_industry": "Relevant business industry",
        "target_customer": "Potential customer type / role",
        "main_benefit": "Why customers need this service",
        "source": "extracted"
      }}
    ],
    "target_audience": {{
      "primary_audience": ["Audience 1", "Audience 2"],
      "secondary_audience": ["Secondary group 1"],
      "industries": ["Industry 1", "Industry 2"],
      "business_types": ["Small Businesses", "Startups", "Enterprise"],
      "customer_profiles": [
        {{
          "audience_type": "Startup Founders",
          "business_type": "Early-Stage Startups",
          "core_requirement": "Rapid MVP Development"
        }}
      ],
      "geographical_focus": "Global / North America / Regional focus based on content",
      "customer_needs": ["Need 1", "Need 2"],
      "customer_interests": ["Interest 1", "Interest 2"],
      "recommended_marketing_segments": ["Segment 1", "Segment 2"]
    }}
  }}
}}
"""
    return prompt


def clean_raw_json(raw_text: str) -> str:
    """Extract clean JSON string by removing markdown code fences and boundary whitespace."""
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[len("```json"):].strip()
    elif text.startswith("```"):
        text = text[3:].strip()

    if text.endswith("```"):
        text = text[:-3].strip()

    # Locate first { and last }
    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        text = text[start_idx : end_idx + 1]

    return text


def is_transient_error(exc: Exception) -> bool:
    """Check if exception represents a transient 503 UNAVAILABLE, 429 RESOURCE_EXHAUSTED, or timeout error."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True

    code = getattr(exc, "code", None)
    status_str = getattr(exc, "status", None)
    if code in (429, 503):
        return True
    if status_str and str(status_str).upper() in ("RESOURCE_EXHAUSTED", "UNAVAILABLE"):
        return True

    # Fallback inspection on error string
    err_str = str(exc).upper()
    return any(
        indicator in err_str
        for indicator in (
            "503",
            "UNAVAILABLE",
            "429",
            "RESOURCE_EXHAUSTED",
            "QUOTA EXCEEDED",
            "RATE LIMIT",
            "TIMED OUT",
            "TIMEOUT",
        )
    )


def execute_llm_call(
    client: genai.Client,
    model_name: str,
    prompt: str,
) -> Tuple[str, TokenUsage]:
    """Execute synchronous call to Gemini API using google-genai SDK."""
    try:
        # Note: for gemini-4-* models, do not pass thinking_budget or custom sampling
        # params (temperature/top_p/top_k) — use default settings or thinking_level="low"
        # to avoid 400 validation errors.
        if model_name.startswith("gemini-4"):
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_level="low"),
            )
        else:
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            )

        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config,
        )
    except Exception as exc:
        logger.error(f"Gemini API call failed for model '{model_name}': {exc}")
        if is_transient_error(exc):
            raise exc
        raise LLMServiceException(f"LLM API request failed: {exc}") from exc

    raw_text = response.text or ""
    if not raw_text:
        raise LLMServiceException("LLM returned an empty response text.")

    token_usage = TokenUsage()
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        um = response.usage_metadata
        token_usage.prompt_tokens = getattr(um, "prompt_token_count", None)
        token_usage.completion_tokens = getattr(um, "candidates_token_count", None)
        token_usage.total_tokens = getattr(um, "total_token_count", None)

    return raw_text, token_usage


async def call_groq_api(
    prompt: str,
    api_key: str,
    model_name: str = "openai/gpt-oss-120b",
    timeout: float = 30.0,
) -> Tuple[BrandInfo, AnalysisResult, str, TokenUsage]:
    """
    Execute cross-provider fallback call to Groq API using async httpx.
    Configured for json_object response format with low/hidden reasoning effort.
    """
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert business intelligence and technical SEO analyst. "
                    "You must output only a valid JSON object matching the requested schema."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "response_format": {"type": "json_object"},
        "reasoning_effort": "low",
        "reasoning_format": "hidden",
        "max_completion_tokens": 4096,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)

        if resp.status_code != 200:
            raise LLMServiceException(
                f"Groq API returned HTTP {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise LLMServiceException("Groq API returned no choices in response.")

        raw_content = choices[0].get("message", {}).get("content", "")
        if not raw_content:
            raise LLMServiceException("Groq API returned empty message content.")

        cleaned = clean_raw_json(raw_content)
        parsed = json.loads(cleaned)

        brand = BrandInfo.model_validate(parsed.get("brand", {}))
        analysis = AnalysisResult.model_validate(parsed.get("analysis", {}))

        usage_dict = data.get("usage", {})
        token_usage = TokenUsage(
            prompt_tokens=usage_dict.get("prompt_tokens"),
            completion_tokens=usage_dict.get("completion_tokens"),
            total_tokens=usage_dict.get("total_tokens"),
        )

        return brand, analysis, model_name, token_usage

    except LLMServiceException:
        raise
    except Exception as exc:
        logger.error(f"Groq API fallback failed: {exc}")
        raise LLMServiceException(f"Groq API fallback request failed: {exc}") from exc


async def analyze_website_with_llm(
    website_context: str,
    competitor_hints: list[str],
    gemini_timeout: float = 20.0,
    inter_model_delay: float = 1.5,
) -> Tuple[BrandInfo, AnalysisResult, str, TokenUsage]:
    """
    Analyze website content with fast failover:
    1. Primary Gemini: gemini-3.5-flash-lite (1 attempt, 20s timeout)
    2. Secondary Gemini: gemini-3.8-flash (1 attempt, 20s timeout, 1.5s delay)
    3. Cross-provider fallback: Groq (openai/gpt-oss-120b) if configured and Gemini fails
    """
    settings = get_settings()
    client = get_genai_client()

    prompt = build_analysis_prompt(website_context, competitor_hints)

    # Gemini model chain: at most 1 attempt per model with 20s timeout
    gemini_models = [
        settings.GEMINI_MODEL or "gemini-3.5-flash-lite",
        settings.GEMINI_FALLBACK_MODEL or "gemini-3.8-flash",
    ]

    last_error: Optional[Exception] = None
    had_transient_error = False

    for attempt_idx, model_name in enumerate(gemini_models):
        try:
            logger.info(
                f"Attempting LLM analysis with Gemini model '{model_name}' "
                f"(model {attempt_idx + 1}/{len(gemini_models)}, max timeout: {gemini_timeout}s)"
            )
            raw_text, token_usage = await asyncio.wait_for(
                asyncio.to_thread(
                    execute_llm_call,
                    client,
                    model_name,
                    prompt,
                ),
                timeout=gemini_timeout,
            )

            cleaned_json = clean_raw_json(raw_text)
            parsed_data = json.loads(cleaned_json)

            # Validate sections
            brand = BrandInfo.model_validate(parsed_data.get("brand", {}))
            analysis = AnalysisResult.model_validate(parsed_data.get("analysis", {}))

            return brand, analysis, model_name, token_usage

        except asyncio.TimeoutError:
            logger.warning(f"Gemini model '{model_name}' timed out after {gemini_timeout}s.")
            last_error = LLMServiceException(f"Gemini model '{model_name}' timed out after {gemini_timeout}s.")
            had_transient_error = True
        except Exception as exc:
            if is_transient_error(exc):
                had_transient_error = True
                logger.warning(f"Transient error on Gemini model '{model_name}': {exc}")
                last_error = exc if isinstance(exc, LLMServiceException) else LLMServiceException(str(exc))
            elif isinstance(exc, (json.JSONDecodeError, ValueError)):
                logger.warning(f"JSON parse error on model '{model_name}': {exc}")
                last_error = LLMServiceException(f"LLM output could not be parsed into required JSON schema: {exc}")
            else:
                logger.warning(f"Error on model '{model_name}': {exc}")
                last_error = exc if isinstance(exc, LLMServiceException) else LLMServiceException(str(exc))

        # Short delay before moving to next Gemini model (if another model remains)
        if attempt_idx < len(gemini_models) - 1:
            logger.info(f"Waiting {inter_model_delay}s before trying next Gemini model...")
            await asyncio.sleep(inter_model_delay)

    # Cross-provider fallback to Groq when Gemini fails
    if settings.GROQ_API_KEY:
        groq_model = settings.GROQ_MODEL or "openai/gpt-oss-120b"
        logger.info(
            f"All Gemini models exhausted (transient_error={had_transient_error}). "
            f"Triggering cross-provider fallback to Groq ({groq_model})..."
        )
        try:
            return await call_groq_api(
                prompt=prompt,
                api_key=settings.GROQ_API_KEY,
                model_name=groq_model,
            )
        except Exception as groq_exc:
            logger.error(f"Groq fallback also failed: {groq_exc}")
            raise LLMServiceException(
                f"Both Gemini and Groq fallback failed. Gemini error: {last_error}; Groq error: {groq_exc}"
            ) from groq_exc

    raise last_error or LLMServiceException("All Gemini LLM analysis attempts failed.")
