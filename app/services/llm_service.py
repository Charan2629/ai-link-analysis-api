import asyncio
import json
import logging
import re
from typing import Any, Dict, Optional, Tuple
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


def execute_llm_call(
    client: genai.Client,
    model_name: str,
    prompt: str,
) -> Tuple[str, TokenUsage]:
    """Execute synchronous call to Gemini API using google-genai SDK."""
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
    except Exception as exc:
        logger.error(f"Gemini API call failed for model '{model_name}': {exc}")
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


async def analyze_website_with_llm(
    website_context: str,
    competitor_hints: list[str],
) -> Tuple[BrandInfo, AnalysisResult, str, TokenUsage]:
    """
    Analyze website content using Google Gemini via google-genai SDK.
    Uses gemini-3.5-flash-lite as primary model with automatic 1-retry fallback.
    """
    settings = get_settings()
    client = get_genai_client()

    prompt = build_analysis_prompt(website_context, competitor_hints)

    models_to_try = [
        settings.GEMINI_MODEL or "gemini-3.5-flash-lite",
        settings.GEMINI_FALLBACK_MODEL or "gemini-3.8-flash",
    ]

    last_error: Optional[Exception] = None

    for attempt_idx, model_name in enumerate(models_to_try):
        try:
            logger.info(f"Attempting LLM analysis with model '{model_name}' (attempt {attempt_idx + 1}/2)")
            raw_text, token_usage = await asyncio.to_thread(
                execute_llm_call,
                client,
                model_name,
                prompt,
            )

            cleaned_json = clean_raw_json(raw_text)
            parsed_data = json.loads(cleaned_json)

            # Validate sections
            brand = BrandInfo.model_validate(parsed_data.get("brand", {}))
            analysis = AnalysisResult.model_validate(parsed_data.get("analysis", {}))

            return brand, analysis, model_name, token_usage

        except (json.JSONDecodeError, ValueError) as json_err:
            logger.warning(
                f"JSON parse error on attempt {attempt_idx + 1} with model '{model_name}': {json_err}"
            )
            last_error = LLMServiceException(
                f"LLM output could not be parsed into required JSON schema: {json_err}"
            )
            continue
        except LLMServiceException as llm_err:
            logger.warning(
                f"LLM execution error on attempt {attempt_idx + 1} with model '{model_name}': {llm_err}"
            )
            last_error = llm_err
            continue

    raise last_error or LLMServiceException("All LLM analysis attempts failed.")
