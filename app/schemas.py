from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, HttpUrl


class LinkAnalysisRequest(BaseModel):
    """Incoming request body for website link analysis."""
    url: str = Field(
        ...,
        description="The full HTTP/HTTPS website URL to analyze.",
        examples=["https://example.com"],
    )


class BrandInfo(BaseModel):
    """Extracted and inferred brand identity information."""
    name: str = Field(..., description="Brand or company name.")
    category: str = Field(..., description="Primary business sector or category.")
    summary: str = Field(..., description="Concise, human-friendly summary of the business.")


class CompetitorItem(BaseModel):
    """Detailed competitor profile compared against the analyzed brand."""
    name: str = Field(..., description="Competitor brand or business name.")
    main_service: str = Field(..., description="Core service or product offering.")
    target_market: str = Field(..., description="Target market segment (e.g., Enterprise, SMB).")
    strengths: List[str] = Field(default_factory=list, description="Key competitor strengths.")
    weaknesses_or_gaps: List[str] = Field(
        default_factory=list,
        description="Identified competitor gaps or weaknesses.",
    )
    source: Literal["extracted", "ai_inferred"] = Field(
        default="ai_inferred",
        description="Whether competitor was explicitly mentioned on site or inferred by AI.",
    )


class CompetitorAnalysis(BaseModel):
    """Section 1: Competitor vs Your Brand Details."""
    brand_overview: str = Field(..., description="Overview of the analyzed brand.")
    main_business_category: str = Field(..., description="Main business category.")
    main_products_and_services: List[str] = Field(
        default_factory=list,
        description="Core products and services offered.",
    )
    competitors: List[CompetitorItem] = Field(
        ...,
        min_length=3,
        description="Minimum 3 identified or inferred competitors.",
    )
    competitive_advantages: List[str] = Field(
        default_factory=list,
        description="Brand strengths and key competitive edges.",
    )
    opportunities: List[str] = Field(
        default_factory=list,
        description="Strategic opportunities to improve market positioning.",
    )


class SearchQueryItem(BaseModel):
    """Individual high-intent search query across target platforms."""
    query: str = Field(..., description="The potential search query string.")
    platforms: List[str] = Field(
        ...,
        description="Applicable search platforms (e.g. Google Search, Facebook, Instagram, LinkedIn, X (Twitter)).",
    )
    intent: str = Field(
        ...,
        description="Search intent (e.g., Service Search, Business Discovery, B2B Search).",
    )
    business_relevance: str = Field(..., description="Relevance to brand offerings.")
    target_audience: str = Field(..., description="Target buyer persona executing this search.")


class SupportingContentItem(BaseModel):
    """Content asset recommendation to improve SEO."""
    content_type: str = Field(
        ...,
        description="Type of content (e.g., Service Landing Page, FAQ, Blog Topic, Industry Guide).",
    )
    title_or_topic: str = Field(..., description="Suggested title or topic.")
    rationale: str = Field(..., description="Why this content improves search visibility.")


class SEOImprovements(BaseModel):
    """Section 3: SEO Improvement Recommendations."""
    primary_keyword: str = Field(..., description="Primary ranking target keyword.")
    secondary_keywords: List[str] = Field(default_factory=list, description="Secondary keywords.")
    long_tail_keywords: List[str] = Field(default_factory=list, description="High-intent long-tail keywords.")
    business_keywords: List[str] = Field(default_factory=list, description="Core industry/business keywords.")
    recommended_title: str = Field(..., description="Optimized SEO title tag.")
    meta_description: str = Field(..., description="Optimized meta description tag.")
    supporting_content: List[SupportingContentItem] = Field(
        default_factory=list,
        description="Recommended supporting pages, landing pages, FAQs, or articles.",
    )


class ServiceItem(BaseModel):
    """Section 4: Core Service Profile."""
    service_name: str = Field(..., description="Name of the service.")
    description: str = Field(..., description="Short explanation of the service.")
    target_industry: str = Field(..., description="Relevant industry vertical.")
    target_customer: str = Field(..., description="Customer profile or buyer role.")
    main_benefit: str = Field(..., description="Primary value proposition or customer outcome.")
    source: Literal["extracted", "ai_inferred"] = Field(
        default="extracted",
        description="Whether identified from actual content or inferred by AI.",
    )


class CustomerProfileItem(BaseModel):
    """Audience segment persona details."""
    audience_type: str = Field(..., description="Persona title or segment name.")
    business_type: str = Field(..., description="SMB, Startup, Enterprise, Consumer, etc.")
    core_requirement: str = Field(..., description="Primary problem they need solved.")


class TargetAudience(BaseModel):
    """Section 5: Target Audience Identification."""
    primary_audience: List[str] = Field(..., description="Primary target audience groups.")
    secondary_audience: List[str] = Field(default_factory=list, description="Secondary target audience groups.")
    industries: List[str] = Field(default_factory=list, description="Target industry verticals.")
    business_types: List[str] = Field(default_factory=list, description="Target business classifications.")
    customer_profiles: List[CustomerProfileItem] = Field(
        default_factory=list,
        description="Detailed customer profile breakdown.",
    )
    geographical_focus: str = Field(..., description="Geographical reach or regional focus.")
    customer_needs: List[str] = Field(default_factory=list, description="Customer pain points and challenges.")
    customer_interests: List[str] = Field(default_factory=list, description="Customer interests and motivations.")
    recommended_marketing_segments: List[str] = Field(
        default_factory=list,
        description="Recommended actionable segments for campaigns.",
    )


class AnalysisResult(BaseModel):
    """Structured container holding all five functional analysis sections."""
    competitor_analysis: CompetitorAnalysis
    target_search_queries: List[SearchQueryItem] = Field(..., min_length=5, max_length=5)
    seo_improvements: SEOImprovements
    top_services: List[ServiceItem] = Field(..., min_length=1)
    target_audience: TargetAudience


class TokenUsage(BaseModel):
    """Token usage reported by LLM provider or estimated."""
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class AnalysisMetadata(BaseModel):
    """Execution telemetry and runtime metadata."""
    model: str = Field(..., description="The LLM model used for the analysis.")
    processing_time_ms: float = Field(..., description="Total execution time in milliseconds.")
    cached: bool = Field(default=False, description="Whether the response was served from cache.")
    token_usage: Optional[TokenUsage] = Field(default=None, description="Reported token counts.")


class LinkAnalysisResponse(BaseModel):
    """Top-level unified API response."""
    success: bool = True
    website: str
    brand: BrandInfo
    analysis: AnalysisResult
    metadata: AnalysisMetadata


class ErrorResponse(BaseModel):
    """Standardized error response payload."""
    success: bool = False
    error: str
    detail: Optional[str] = None
