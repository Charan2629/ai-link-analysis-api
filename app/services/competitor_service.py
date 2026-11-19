import re
from typing import List, Tuple
from app.schemas import CompetitorItem


def find_explicit_competitor_mentions(page_text: str) -> List[str]:
    """
    Search extracted page text for explicit competitor mentions,
    such as 'vs', 'alternative to', 'compared to', or comparison tables.
    """
    patterns = [
        r"(?:alternative to|versus|vs\.?|compared to|better than)\s+([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)?)",
        r"(?:switch from|migrate from)\s+([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)?)",
    ]
    found: List[str] = []
    for pattern in patterns:
        matches = re.findall(pattern, page_text, flags=re.IGNORECASE)
        for match in matches:
            cleaned = match.strip()
            if len(cleaned) > 2 and cleaned not in found:
                found.append(cleaned)
    return found


def enrich_and_validate_competitors(
    competitors: List[CompetitorItem],
    page_text: str,
) -> List[CompetitorItem]:
    """
    Verify competitor sources (mark 'extracted' if mentioned on the page,
    otherwise ensure labeled as 'ai_inferred').
    """
    page_lower = page_text.lower()
    enriched: List[CompetitorItem] = []

    for comp in competitors:
        is_in_text = comp.name.lower() in page_lower if comp.name else False
        source = "extracted" if is_in_text else "ai_inferred"
        enriched.append(
            CompetitorItem(
                name=comp.name,
                main_service=comp.main_service,
                target_market=comp.target_market,
                strengths=comp.strengths,
                weaknesses_or_gaps=comp.weaknesses_or_gaps,
                source=source,
            )
        )

    return enriched
