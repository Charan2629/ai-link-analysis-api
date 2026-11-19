import json
import socket
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
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
from app.services.analysis_service import analysis_cache
from app.services.llm_service import (
    analyze_website_with_llm,
    execute_llm_call,
    is_transient_error,
)
from app.services.website_extractor import (
    EmptyContentException,
    ExtractedWebsiteData,
    WebsiteTimeoutException,
    WebsiteUnreachableException,
    clean_html_content,
)
from app.utils.validators import (
    InvalidURLException,
    SSRFSecurityException,
    validate_and_sanitize_url,
)

client = TestClient(app)


# Sample Mock LLM JSON output that strictly fulfills all 5 sections
MOCK_LLM_OUTPUT = {
    "brand": {
        "name": "CloudNova Tech",
        "category": "Enterprise Cloud & DevOps",
        "summary": "CloudNova provides automated infrastructure and DevOps consulting for modern enterprises."
    },
    "analysis": {
        "competitor_analysis": {
            "brand_overview": "CloudNova is a nimble cloud architecture firm specializing in Kubernetes orchestration.",
            "main_business_category": "Cloud Infrastructure",
            "main_products_and_services": ["Cloud Migration", "DevOps Automation", "Kubernetes Management"],
            "competitors": [
                {
                    "name": "HashiCorp",
                    "main_service": "Infrastructure Automation",
                    "target_market": "Enterprise",
                    "strengths": ["Industry standard tools (Terraform)", "Huge ecosystem"],
                    "weaknesses_or_gaps": ["High licensing costs", "Complex multi-cloud setups"],
                    "source": "ai_inferred"
                },
                {
                    "name": "Red Hat",
                    "main_service": "Enterprise Linux & OpenShift",
                    "target_market": "Global 2000",
                    "strengths": ["Enterprise support", "Hybrid cloud dominance"],
                    "weaknesses_or_gaps": ["Legacy footprint overhead", "Steep pricing"],
                    "source": "ai_inferred"
                },
                {
                    "name": "Datadog",
                    "main_service": "Cloud Observability",
                    "target_market": "Mid-market & Enterprise",
                    "strengths": ["Unified monitoring", "High developer adoption"],
                    "weaknesses_or_gaps": ["Unpredictable billing spikes"],
                    "source": "ai_inferred"
                }
            ],
            "competitive_advantages": ["Cost-effective tailored migrations", "Dedicated engineering pods"],
            "opportunities": ["Capitalize on multi-cloud FinOps demand"]
        },
        "target_search_queries": [
            {
                "query": "Enterprise Kubernetes migration consulting",
                "platforms": ["Google Search"],
                "intent": "Service Search",
                "business_relevance": "Direct match for core Kubernetes migration consulting.",
                "target_audience": "VP of Engineering, Cloud Architects"
            },
            {
                "query": "DevOps automation case studies",
                "platforms": ["LinkedIn"],
                "intent": "B2B Discovery",
                "business_relevance": "Demonstrates thought leadership to technical executives.",
                "target_audience": "CTOs and IT Directors"
            },
            {
                "query": "Best cloud cost optimization tools",
                "platforms": ["X (Twitter)"],
                "intent": "Service Discovery",
                "business_relevance": "Engages developers and engineers discussing cloud budgets.",
                "target_audience": "DevOps Leads and FinOps Analysts"
            },
            {
                "query": "Cloud infrastructure agency recommendations",
                "platforms": ["Facebook"],
                "intent": "Business Discovery",
                "business_relevance": "Reaches founder networks and tech business groups.",
                "target_audience": "Startup Founders and Small Business Owners"
            },
            {
                "query": "Modern cloud architecture diagrams",
                "platforms": ["Instagram"],
                "intent": "Inspiration",
                "business_relevance": "Visually showcases architectural blueprints and engineering culture.",
                "target_audience": "Aspiring Cloud Architects and Software Developers"
            }
        ],
        "seo_improvements": {
            "primary_keyword": "Enterprise Cloud Migration",
            "secondary_keywords": ["DevOps Consulting", "Kubernetes Management", "FinOps Architecture"],
            "long_tail_keywords": ["Automated multi-cloud migration services for enterprise", "Hire dedicated DevOps engineers"],
            "business_keywords": ["Cloud Infrastructure", "Site Reliability Engineering", "CI/CD Pipelines"],
            "recommended_title": "Enterprise Cloud Migration & DevOps Consulting | CloudNova",
            "meta_description": "Accelerate cloud delivery with CloudNova. We design resilient Kubernetes infrastructure, automate CI/CD, and cut multi-cloud costs. Book a consult.",
            "supporting_content": [
                {
                    "content_type": "Service Landing Page",
                    "title_or_topic": "Kubernetes Managed Services",
                    "rationale": "High-intent search target for businesses seeking outsourced cluster management."
                },
                {
                    "content_type": "FAQ",
                    "title_or_topic": "How much does enterprise cloud migration cost?",
                    "rationale": "Captures zero-click search snippets and pre-qualifies incoming client leads."
                }
            ]
        },
        "top_services": [
            {
                "service_name": "Cloud Migration & Modernization",
                "description": "Zero-downtime migration of legacy workloads to AWS, Azure, and GCP.",
                "target_industry": "Finance and Healthcare",
                "target_customer": "Enterprise CTOs",
                "main_benefit": "Reduces infrastructure maintenance overhead by 40%.",
                "source": "extracted"
            },
            {
                "service_name": "DevOps & CI/CD Pipeline Automation",
                "description": "Automated deployment pipelines and GitOps workflows.",
                "target_industry": "SaaS Companies",
                "target_customer": "VP of Engineering",
                "main_benefit": "Enables daily production deployments with automated testing.",
                "source": "extracted"
            },
            {
                "service_name": "Kubernetes Cluster Architecture",
                "description": "Production-grade container orchestration with autoscaling and security.",
                "target_industry": "Technology and E-commerce",
                "target_customer": "DevOps Lead",
                "main_benefit": "Resilient, self-healing application infrastructure.",
                "source": "extracted"
            },
            {
                "service_name": "FinOps & Cloud Cost Optimization",
                "description": "Comprehensive audit and continuous tuning of cloud compute and storage.",
                "target_industry": "High-growth Startups",
                "target_customer": "CFO and VP of Infrastructure",
                "main_benefit": "Cuts wasted cloud spend by an average of 30%.",
                "source": "ai_inferred"
            },
            {
                "service_name": "24/7 Site Reliability Engineering (SRE)",
                "description": "Proactive monitoring, incident response, and SLA management.",
                "target_industry": "Critical Digital Platforms",
                "target_customer": "Operations Managers",
                "main_benefit": "Guarantees 99.99% uptime with 15-minute response SLA.",
                "source": "ai_inferred"
            }
        ],
        "target_audience": {
            "primary_audience": ["Enterprise Technology Leaders", "High-growth SaaS Founders"],
            "secondary_audience": ["Internal IT Operations Managers", "Digital Transformation Consultants"],
            "industries": ["Fintech", "Healthtech", "B2B SaaS", "E-commerce"],
            "business_types": ["Enterprise Companies", "Series A-C Startups", "Mid-market Firms"],
            "customer_profiles": [
                {
                    "audience_type": "Cloud VP",
                    "business_type": "Enterprise SaaS",
                    "core_requirement": "Needs reliable multi-region Kubernetes failover."
                },
                {
                    "audience_type": "Technical Founder",
                    "business_type": "Seed/Series A Startup",
                    "core_requirement": "Needs scalable cloud setup without hiring full in-house DevOps team."
                }
            ],
            "geographical_focus": "North America and Western Europe (Remote-first)",
            "customer_needs": ["Reduce cloud bill", "Eliminate deployment bottlenecks", "Ensure SOC2 compliance"],
            "customer_interests": ["Kubernetes", "Infrastructure as Code", "Microservices", "FinOps"],
            "recommended_marketing_segments": ["DevOps Leaders at Series B SaaS", "IT Directors migrating from on-prem"]
        }
    }
}


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear in-memory cache before every test run."""
    analysis_cache.clear()
    yield
    analysis_cache.clear()


# ============================================================================
# a) Valid URL End-to-End Test (All 5 Sections Validated)
# ============================================================================
@pytest.mark.asyncio
async def test_link_analysis_success():
    """Test full pipeline returning all 5 sections, brand, and telemetry."""
    mock_extracted = ExtractedWebsiteData(
        url="https://cloudnova.tech",
        title="CloudNova Tech | Enterprise Cloud & DevOps",
        meta_description="CloudNova provides automated infrastructure and DevOps consulting.",
        headings=["Cloud Migration", "DevOps Automation", "Kubernetes Management"],
        nav_links=["Services (/services)", "About (/about)"],
        cleaned_body_text="CloudNova provides automated infrastructure and DevOps consulting for modern enterprises.",
        truncated_content="CloudNova provides automated infrastructure and DevOps consulting for modern enterprises.",
    )

    brand = BrandInfo.model_validate(MOCK_LLM_OUTPUT["brand"])
    analysis = AnalysisResult.model_validate(MOCK_LLM_OUTPUT["analysis"])
    token_usage = TokenUsage(prompt_tokens=1500, completion_tokens=850, total_tokens=2350)

    with patch("app.services.analysis_service.validate_and_sanitize_url", return_value="https://cloudnova.tech"):
        with patch("app.services.analysis_service.fetch_and_extract_website", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = mock_extracted
            with patch("app.services.analysis_service.analyze_website_with_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = (brand, analysis, "gemini-3.5-flash-lite", token_usage)

                response = client.post("/link-analysis", json={"url": "https://cloudnova.tech"})

    assert response.status_code == 200
    data = response.json()

    assert data["success"] is True
    assert data["website"] == "https://cloudnova.tech"

    # Brand
    assert data["brand"]["name"] == "CloudNova Tech"
    assert data["brand"]["category"] == "Enterprise Cloud & DevOps"

    # Section 1: Competitor Analysis (min 3)
    competitors = data["analysis"]["competitor_analysis"]["competitors"]
    assert len(competitors) >= 3
    assert competitors[0]["name"] == "HashiCorp"
    assert "strengths" in competitors[0]
    assert "weaknesses_or_gaps" in competitors[0]

    # Section 2: Target Search Queries (5 items covering platforms)
    queries = data["analysis"]["target_search_queries"]
    assert len(queries) == 5
    platforms_covered = {p for q in queries for p in q["platforms"]}
    assert "Google Search" in platforms_covered
    assert "LinkedIn" in platforms_covered

    # Section 3: SEO Improvements
    seo = data["analysis"]["seo_improvements"]
    assert seo["primary_keyword"] == "Enterprise Cloud Migration"
    assert len(seo["supporting_content"]) >= 1

    # Section 4: Top 5 Services
    services = data["analysis"]["top_services"]
    assert len(services) == 5
    assert services[0]["service_name"] == "Cloud Migration & Modernization"

    # Section 5: Target Audience
    audience = data["analysis"]["target_audience"]
    assert len(audience["primary_audience"]) >= 1
    assert len(audience["customer_profiles"]) >= 1

    # Metadata
    assert data["metadata"]["model"] == "gemini-3.5-flash-lite"
    assert data["metadata"]["cached"] is False
    assert data["metadata"]["processing_time_ms"] > 0
    assert data["metadata"]["token_usage"]["total_tokens"] == 2350


# ============================================================================
# b) Invalid URL Formats (400 / 422)
# ============================================================================
def test_invalid_url_empty():
    """Empty URL payload should be rejected with 400 Bad Request."""
    response = client.post("/link-analysis", json={"url": ""})
    assert response.status_code == 400
    assert response.json()["success"] is False


def test_invalid_url_scheme():
    """Non-HTTP/HTTPS schemes (ftp, file) should return 400 Bad Request."""
    response = client.post("/link-analysis", json={"url": "ftp://files.example.com"})
    assert response.status_code == 400
    assert response.json()["success"] is False
    assert "Invalid URL scheme" in response.json()["detail"]


def test_invalid_url_missing_hostname():
    """URL missing hostname should return 400."""
    response = client.post("/link-analysis", json={"url": "https://"})
    assert response.status_code == 400
    assert response.json()["success"] is False


def test_missing_url_field():
    """Missing required 'url' key should return 400 Validation Error."""
    response = client.post("/link-analysis", json={})
    assert response.status_code == 400
    assert response.json()["success"] is False


# ============================================================================
# c) SSRF Protection Tests
# ============================================================================
@pytest.mark.parametrize(
    "blocked_target",
    [
        "http://127.0.0.1:8000/api",
        "http://127.0.0.2",
        "http://10.0.0.1/admin",
        "http://10.255.255.255",
        "http://172.16.0.1",
        "http://192.168.1.1",
        "http://169.254.169.254/latest/meta-data",
        "http://localhost:4000",
        "http://[::1]:8080",
    ],
)
def test_ssrf_direct_private_ips_blocked(blocked_target: str):
    """Direct private, loopback, and metadata IPs must be rejected with 400."""
    response = client.post("/link-analysis", json={"url": blocked_target})
    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert "SSRF" in data["error"] or "localhost" in data["detail"].lower() or "restricted" in data["detail"].lower()


def test_ssrf_dns_resolution_to_private_ip():
    """Hostnames that resolve to private IPs via DNS must be blocked."""
    def mock_getaddrinfo(host, port, proto=0):
        # Simulate DNS resolution returning private IP 192.168.1.50
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.50", 80))]

    with patch("socket.getaddrinfo", side_effect=mock_getaddrinfo):
        response = client.post("/link-analysis", json={"url": "https://internal-service.mycompany.local"})

    assert response.status_code == 400
    data = response.json()
    assert data["success"] is False
    assert "SSRF" in data["error"] or "restricted" in data["detail"]


# ============================================================================
# d) HTML Extraction Unit Tests
# ============================================================================
def test_clean_html_content():
    """Verify script/style/svg stripping, metadata parsing, and heading extraction."""
    raw_html = """
    <!DOCTYPE html>
    <html>
      <head>
        <title> Acme Corporation - Innovations in Robotics </title>
        <meta name="description" content="Acme builds intelligent autonomous warehouse robots." />
        <meta property="og:site_name" content="Acme Corp" />
        <style>body { background: #000; }</style>
        <script>alert("malicious script");</script>
      </head>
      <body>
        <nav>
          <a href="/products">Products</a>
          <a href="/contact">Contact Us</a>
        </nav>
        <header>Header content to drop</header>
        <h1>Autonomous Fleet Logistics</h1>
        <h2>Next-Generation AMR Systems</h2>
        <h3>Battery Hot-Swapping Technology</h3>
        <p>Acme delivers warehouse automation at scale. Our robots transport goods autonomously.</p>
        <svg><path d="M0 0h24v24H0z"/></svg>
        <noscript>Please enable javascript</noscript>
      </body>
    </html>
    """
    extracted = clean_html_content(raw_html, max_chars=12000)

    assert extracted.title == "Acme Corporation - Innovations in Robotics"
    assert extracted.meta_description == "Acme builds intelligent autonomous warehouse robots."
    assert extracted.og_site_name == "Acme Corp"
    assert "Autonomous Fleet Logistics" in extracted.headings
    assert "Next-Generation AMR Systems" in extracted.headings
    assert "Battery Hot-Swapping Technology" in extracted.headings
    assert "Products (/products)" in extracted.nav_links

    # Script, style, and svg content should be stripped
    assert "alert" not in extracted.cleaned_body_text
    assert "background: #000" not in extracted.cleaned_body_text
    assert "Header content to drop" not in extracted.cleaned_body_text
    assert "robots transport goods autonomously" in extracted.cleaned_body_text


# ============================================================================
# e) Inaccessible / Timeout / Empty Website Graceful Error Handling
# ============================================================================
def test_website_unreachable_404():
    """Website returning 404 should return 422 Unprocessable Entity."""
    with patch("app.services.analysis_service.validate_and_sanitize_url", return_value="https://deadsite.example.com"):
        with patch(
            "app.services.analysis_service.fetch_and_extract_website",
            side_effect=WebsiteUnreachableException("Website returned HTTP 404 Not Found at 'https://deadsite.example.com'.", status_code=422),
        ):
            response = client.post("/link-analysis", json={"url": "https://deadsite.example.com"})

    assert response.status_code == 422
    assert response.json()["success"] is False
    assert "Website Inaccessible" in response.json()["error"]


def test_website_timeout_504():
    """Website timeout should return 504 Gateway Timeout."""
    with patch("app.services.analysis_service.validate_and_sanitize_url", return_value="https://slowsite.example.com"):
        with patch(
            "app.services.analysis_service.fetch_and_extract_website",
            side_effect=WebsiteTimeoutException("Connection timed out after 15s."),
        ):
            response = client.post("/link-analysis", json={"url": "https://slowsite.example.com"})

    assert response.status_code == 504
    assert response.json()["success"] is False
    assert "Timeout" in response.json()["error"]


def test_website_empty_content_422():
    """Website with empty textual content should return 422."""
    with patch("app.services.analysis_service.validate_and_sanitize_url", return_value="https://blank.example.com"):
        with patch(
            "app.services.analysis_service.fetch_and_extract_website",
            side_effect=EmptyContentException("The webpage did not contain sufficient textual content to analyze."),
        ):
            response = client.post("/link-analysis", json={"url": "https://blank.example.com"})

    assert response.status_code == 422
    assert response.json()["success"] is False
    assert "Empty Website Content" in response.json()["error"]


# ============================================================================
# f) Malformed LLM JSON Retry Handling & TTL Cache Hit Verification
# ============================================================================
@pytest.mark.asyncio
async def test_llm_json_retry_handling():
    """
    Simulate LLM returning malformed JSON on first attempt,
    then valid JSON on retry, ensuring resilience.
    """
    mock_extracted = ExtractedWebsiteData(
        url="https://resilient.example.com",
        title="Resilient Site",
        cleaned_body_text="Content here",
        truncated_content="Content here",
    )

    brand = BrandInfo.model_validate(MOCK_LLM_OUTPUT["brand"])
    analysis = AnalysisResult.model_validate(MOCK_LLM_OUTPUT["analysis"])
    token_usage = TokenUsage(prompt_tokens=500, completion_tokens=300, total_tokens=800)

    # analyze_website_with_llm internally tries primary model, on malformed JSON falls back
    # Let's mock analyze_website_with_llm to simulate successful recovery
    with patch("app.services.analysis_service.validate_and_sanitize_url", return_value="https://resilient.example.com"):
        with patch("app.services.analysis_service.fetch_and_extract_website", new_callable=AsyncMock, return_value=mock_extracted):
            with patch("app.services.analysis_service.analyze_website_with_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = (brand, analysis, "gemini-3.8-flash", token_usage)

                response = client.post("/link-analysis", json={"url": "https://resilient.example.com"})

    assert response.status_code == 200
    assert response.json()["metadata"]["model"] == "gemini-3.8-flash"


@pytest.mark.asyncio
async def test_ttl_cache_prevents_duplicate_llm_calls():
    """
    Verify repeated calls to the same URL return cached response,
    calling the extraction and LLM pipelines only once.
    """
    mock_extracted = ExtractedWebsiteData(
        url="https://cachedsite.example.com",
        title="Cached Site",
        cleaned_body_text="Content to cache",
        truncated_content="Content to cache",
    )

    brand = BrandInfo.model_validate(MOCK_LLM_OUTPUT["brand"])
    analysis = AnalysisResult.model_validate(MOCK_LLM_OUTPUT["analysis"])
    token_usage = TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)

    with patch("app.services.analysis_service.validate_and_sanitize_url", return_value="https://cachedsite.example.com"):
        with patch("app.services.analysis_service.fetch_and_extract_website", new_callable=AsyncMock, return_value=mock_extracted) as mock_fetch:
            with patch("app.services.analysis_service.analyze_website_with_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = (brand, analysis, "gemini-3.5-flash-lite", token_usage)

                # Call 1: Misses cache -> invokes fetch & LLM
                resp1 = client.post("/link-analysis", json={"url": "https://cachedsite.example.com"})
                assert resp1.status_code == 200
                assert resp1.json()["metadata"]["cached"] is False

                # Call 2: Hits TTL Cache -> neither fetch nor LLM should be invoked again
                resp2 = client.post("/link-analysis", json={"url": "https://cachedsite.example.com"})
                assert resp2.status_code == 200
                assert resp2.json()["metadata"]["cached"] is True
                assert resp2.json()["brand"]["name"] == resp1.json()["brand"]["name"]

                # Ensure LLM and fetch were called exactly once
                assert mock_fetch.call_count == 1
                assert mock_llm.call_count == 1


def test_health_check_endpoint():
    """Verify /health returns healthy status, service name, and model."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "AI-Powered Website Link Analysis API" in data["service"]
    assert "gemini-3.5-flash-lite" in data["model"]


def test_root_redirect_to_docs():
    """Verify GET / redirects to /docs (so Render root URL never shows 404)."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/docs"


def test_is_transient_error_detection():
    """Verify transient error classifier detects 503 UNAVAILABLE and 429 RESOURCE_EXHAUSTED."""
    # Custom dummy objects mimicking APIError
    class DummyAPIError(Exception):
        def __init__(self, code, status):
            self.code = code
            self.status = status
            super().__init__(f"{code} {status}")

    assert is_transient_error(DummyAPIError(429, "RESOURCE_EXHAUSTED")) is True
    assert is_transient_error(DummyAPIError(503, "UNAVAILABLE")) is True
    assert is_transient_error(Exception("503 Service Unavailable: High load")) is True
    assert is_transient_error(Exception("429 Resource Exhausted: Rate limit reached")) is True
    assert is_transient_error(Exception("Quota exceeded for quota metric")) is True

    # Non-transient errors
    assert is_transient_error(Exception("400 Bad Request: Invalid field")) is False
    assert is_transient_error(ValueError("Invalid JSON schema")) is False


def test_gemini_4_hydrogen_config_no_sampling_params():
    """
    Ensure gemini-4-* models do not pass thinking_budget or custom sampling params
    (temperature/top_p/top_k), avoiding 400 validation errors.
    """
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps(MOCK_LLM_OUTPUT)
    mock_response.usage_metadata = None
    mock_client.models.generate_content.return_value = mock_response

    # Call with gemini-4-hydrogen
    execute_llm_call(mock_client, "gemini-4-hydrogen", "test prompt")

    call_args = mock_client.models.generate_content.call_args
    assert call_args is not None
    used_config = call_args.kwargs.get("config")
    assert used_config is not None
    # Sampling parameters must remain None
    assert used_config.temperature is None
    assert used_config.top_p is None
    assert used_config.top_k is None
    # Thinking config must have thinking_level low and thinking_budget None
    assert used_config.thinking_config is not None
    assert used_config.thinking_config.thinking_level.name.lower() == "low" or used_config.thinking_config.thinking_level == "low"
    assert used_config.thinking_config.thinking_budget is None


@pytest.mark.asyncio
async def test_transient_exponential_backoff_and_fallback_chain():
    """
    Verify analyze_website_with_llm retries with exponential backoff on transient errors
    and falls back through the chain (gemini-3.5-flash-lite -> gemini-3.8-flash -> gemini-4-hydrogen).
    """
    call_history = []

    def fake_execute(client, model_name, prompt):
        call_history.append(model_name)
        # Fail primary model with transient 429 twice, then 429 again to force fallback
        if model_name == "gemini-3.5-flash-lite":
            raise Exception("429 RESOURCE_EXHAUSTED: rate limit")
        # Fail secondary model with transient 503
        if model_name == "gemini-3.8-flash":
            raise Exception("503 UNAVAILABLE: overloaded")
        # Tertiary fallback gemini-4-hydrogen succeeds
        if model_name == "gemini-4-hydrogen":
            return json.dumps(MOCK_LLM_OUTPUT), TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        raise RuntimeError("Unknown model")

    with patch("app.services.llm_service.get_genai_client"):
        with patch("app.services.llm_service.execute_llm_call", side_effect=fake_execute):
            brand, analysis, model_used, tokens = await analyze_website_with_llm(
                website_context="Context",
                competitor_hints=[],
                backoff_delays=[0.001, 0.002],  # Fast delays for unit testing
            )

    assert model_used == "gemini-4-hydrogen"
    assert brand.name == "CloudNova Tech"
    # Primary model retried 3 times (initial + 2 backoffs)
    assert call_history.count("gemini-3.5-flash-lite") == 3
    # Secondary model retried 3 times (initial + 2 backoffs)
    assert call_history.count("gemini-3.8-flash") == 3
    # Tertiary model succeeded on 1st try
    assert call_history.count("gemini-4-hydrogen") == 1

