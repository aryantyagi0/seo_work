"""
SELECT Primitive: Find elements using CSS/XPath/regex/JSONPath
Enhanced with XPath support, XML Element handling, and XML content detection.
"""
import re
import xml.etree.ElementTree as ET
from typing import Any, List, Dict, Optional
from bs4 import BeautifulSoup, Tag
from utils.logging_config import get_logger

logger = get_logger("SELECT")


def _xpath_to_css(xpath: str) -> str:
    """
    Convert simple XPath expressions to CSS selectors.
    Handles patterns like //tag1/tag2 -> tag1 tag2, //tag -> tag
    """
    path = xpath.lstrip("/")
    parts = [p.strip() for p in path.split("/") if p.strip()]
    return " ".join(parts)


def _select_from_xml_element(element: Any, selector: str, mode: str) -> Any:
    """
    Select from XML element objects.
    Handles namespaced XML (sitemaps, RSS feeds, etc.).
    """
    try:
        tag_path = selector.lstrip("/")
        parts = [p.strip() for p in tag_path.split("/") if p.strip()]
        results = []

        if len(parts) >= 2:
            # Find all child tags inside parent tags
            # e.g., //url/loc -> find all 'loc' children inside 'url' parents
            parent_tag = parts[-2]
            child_tag = parts[-1]
            for parent in element.iter():
                local_name = parent.tag.split("}")[-1] if "}" in parent.tag else parent.tag
                if local_name == parent_tag:
                    for child in parent:
                        child_local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                        if child_local == child_tag:
                            results.append(child.text or "")
        elif len(parts) == 1:
            # Find all tags with given name
            # e.g., //loc -> find all tags named 'loc'
            target_tag = parts[0]
            for elem in element.iter():
                local_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if local_name == target_tag:
                    results.append(elem.text or "")

        if mode == "exists":
            return len(results) > 0
        elif mode == "one":
            return results[0] if results else None
        else:
            return results
    except Exception as e:
        logger.error(f"SELECT (XML Element) error: {e}")
        return None if mode == "one" else (False if mode == "exists" else [])


def _try_parse_xml(content_str: str) -> Optional[ET.Element]:
    """Attempt to parse string as XML. Returns Element or None if parsing fails."""
    try:
        return ET.fromstring(content_str)
    except ET.ParseError:
        return None


async def select(content: Any, selector: str, mode: str = "one") -> Any:
    """
    Select elements from content

    Args:
        content: HTML string, BeautifulSoup object, XML Element, or text
        selector: CSS selector, xpath (//path), or regex pattern (prefix with "regex:")
        mode: "one" (single), "many" (list), "exists" (boolean)

    Returns:
        - mode="one": Single element or None
        - mode="many": List of elements
        - mode="exists": Boolean
    """
    try:
        # Handle None input
        if content is None:
            logger.warning("SELECT received None content")
            return None if mode == "one" else (False if mode == "exists" else [])

        # Handle xml.etree.ElementTree.Element objects (from TRANSFORM parse_xml)
        if isinstance(content, ET.Element):
            return _select_from_xml_element(content, selector, mode)

        # Handle dict content (e.g., from FETCH result - extract the 'content' field)
        if isinstance(content, dict):
            content = content.get("content") or content.get("html") or ""
            if not content:
                return None if mode == "one" else (False if mode == "exists" else [])

        # Handle input types gracefully
        if not isinstance(content, (str, BeautifulSoup)):
            logger.warning(f"SELECT received unexpected type: {type(content).__name__}")
            return None if mode == "one" else (False if mode == "exists" else [])

        # Parse content based on type
        soup = None
        if isinstance(content, str):
            content_stripped = content.strip()
            # Detect XML content (sitemaps, RSS feeds)
            is_xml = (
                content_stripped.startswith("<?xml")
                or "<urlset" in content_stripped[:500]
                or "<sitemapindex" in content_stripped[:500]
                or "<rss" in content_stripped[:200]
            )
            if is_xml:
                xml_root = _try_parse_xml(content)
                if xml_root is not None:
                    return _select_from_xml_element(xml_root, selector, mode)
                # Fallback to parse XML as HTML
                soup = BeautifulSoup(content, "lxml")
            elif content_stripped.startswith("<") or "<html" in content.lower()[:500]:
                soup = BeautifulSoup(content, "lxml")
            else:
                soup = None
        elif isinstance(content, BeautifulSoup):
            soup = content

        # Regex-based selection
        if selector.startswith("regex:"):
            pattern = selector[6:]
            if soup:
                text = soup.get_text()
                raw_html = str(content) if isinstance(content, str) else ""
                matches = re.findall(pattern, text, re.IGNORECASE)
                if not matches and raw_html:
                    matches = re.findall(pattern, raw_html, re.IGNORECASE)
            else:
                text = str(content)
                matches = re.findall(pattern, text, re.IGNORECASE)

            if mode == "exists":
                return len(matches) > 0
            elif mode == "one":
                return matches[0] if matches else None
            else:
                return matches

        # Convert XPath-style selectors to CSS
        actual_selector = selector
        if selector.startswith("//") or selector.startswith("/"):
            actual_selector = _xpath_to_css(selector)
            logger.debug(f"Converted XPath '{selector}' to CSS '{actual_selector}'")

        # CSS selection (requires parsed soup)
        if not soup:
            logger.warning("SELECT requires HTML content for CSS selectors")
            return None if mode == "one" else (False if mode == "exists" else [])

        if mode == "exists":
            return soup.select_one(actual_selector) is not None
        elif mode == "one":
            return soup.select_one(actual_selector)
        else:  # many
            return soup.select(actual_selector)

    except Exception as e:
        logger.error(f"SELECT error: {e}")
        return None if mode == "one" else (False if mode == "exists" else [])
