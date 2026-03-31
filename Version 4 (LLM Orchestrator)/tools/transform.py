"""
TRANSFORM Primitive: Convert, clean, parse data
"""
import json
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlparse, urljoin, urlunparse, parse_qs
from utils.logging_config import get_logger

logger = get_logger("TRANSFORM")


async def transform(data: Any, operation: str, **kwargs) -> Any:
    """
    Transform data with support for 30+ operations
    
    Args:
        data: Input data (can be str, dict, list, etc.)
        operation: Transform operation name
        **kwargs: Additional parameters like xpath_expr, field_name, delimiter
    
    Returns:
        Transformed data
    """
    try:
        # URL transformation operations
        if operation == "build_url":
            # Convert dict like {'scheme': 'https', 'domain': 'x.com', 'path': '/y'} to URL string
            if isinstance(data, dict):
                scheme = data.get("scheme", "https")
                domain = data.get("domain", "")
                path = data.get("path", "")
                query = data.get("query", "")
                return f"{scheme}://{domain}{path}{'?' + query if query else ''}"
            return str(data)
        
        elif operation == "normalize_url" or operation == "normalize_urls":
            def normalize_single(url):
                if not url:
                    return ""
                if isinstance(url, dict):
                    url = f"{url.get('scheme', 'https')}://{url.get('domain', '')}{url.get('path', '')}"
                parsed = urlparse(str(url))
                normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                return normalized.rstrip("/")
            
            if isinstance(data, list):
                return [normalize_single(u) for u in data]
            return normalize_single(data)
        
        elif operation == "resolve_url" or operation == "join_url":
            # Join base URL + relative path
            base = kwargs.get("base_url", "")
            if not base and isinstance(data, dict):
                base = data.get("base_url", "")
                data = data.get("path", data)
            return urljoin(base, str(data)) if base else str(data)
        
        elif operation == "extract_domain":
            if isinstance(data, dict):
                return data.get("domain", "")
            parsed = urlparse(str(data))
            return parsed.netloc
        
        elif operation == "extract_origin":
            if isinstance(data, dict):
                return f"{data.get('scheme', 'https')}://{data.get('domain', '')}"
            parsed = urlparse(str(data))
            return f"{parsed.scheme}://{parsed.netloc}"
        
        elif operation == "extract_protocol":
            if isinstance(data, dict):
                return data.get("scheme", "")
            parsed = urlparse(str(data))
            return parsed.scheme
        
        elif operation == "extract_params":
            if isinstance(data, dict):
                return data.get("query", {})
            parsed = urlparse(str(data))
            return parse_qs(parsed.query)
        
        # === XML/HTML Operations ===
        elif operation == "xpath":
            xpath_expr = kwargs.get("xpath_expr", kwargs.get("expression", ""))
            if not xpath_expr:
                logger.warning("xpath operation missing xpath_expr parameter")
                return []
            
            from lxml import etree
            if isinstance(data, str):
                parser = etree.HTMLParser()
                tree = etree.fromstring(data.encode(), parser)
            else:
                tree = data
            
            result = tree.xpath(xpath_expr)
            return [elem.text if hasattr(elem, 'text') else str(elem) for elem in result]
        
        elif operation == "extract_tag_names":
            # Extract all tag names from HTML
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(str(data), "lxml")
            return [tag.name for tag in soup.find_all()]
        
        # Data extraction operations
        elif operation == "pluck" or operation == "get_field" or operation == "extract_field":
            # Extract specific field from dict or list of dicts
            field = kwargs.get("field_name", kwargs.get("field", ""))        
            if isinstance(data, dict):
                return data.get(field)
            elif isinstance(data, list):
                return [item.get(field) if isinstance(item, dict) else None for item in data]
            return None
        
        elif operation == "extract_schema_types":
            if isinstance(data, list):
                types = []
                for item in data:
                    if isinstance(item, dict) and "@type" in item:
                        types.append(item["@type"])
                return types
            elif isinstance(data, dict) and "@type" in data:
                return [data["@type"]]
            return []
        
        # === List Operations ===
        elif operation == "lowercase_list":
            if isinstance(data, list):
                return [str(item).lower() if item else "" for item in data]
            return [str(data).lower()]
        
        elif operation == "normalize_url_list":
            if not isinstance(data, list):
                data = [data]
            result = []
            for url in data:
                if isinstance(url, dict):
                    url = f"{url.get('scheme', 'https')}://{url.get('domain', '')}{url.get('path', '')}"
                parsed = urlparse(str(url))
                normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
                result.append(normalized)
            return result
        
        # === JSON Operations ===
        elif operation == "parse_json":
            if isinstance(data, str):
                return json.loads(data)
            return data
        
        elif operation == "parse_json_list":
            if isinstance(data, str):
                parsed = json.loads(data)
                return parsed if isinstance(parsed, list) else [parsed]
            return data if isinstance(data, list) else [data]
        
        elif operation == "jsonld_to_nodes":
            # Extract JSON-LD nodes from HTML or string
            if isinstance(data, str):
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(data, "lxml")
                scripts = soup.find_all("script", {"type": "application/ld+json"})
                nodes = []
                for script in scripts:
                    try:
                        nodes.append(json.loads(script.string))
                    except:
                        pass
                return nodes
            return data if isinstance(data, list) else [data]
        
        # === Math/Logic Operations ===
        elif operation in ("compute_percentage", "calculate_percentage"):
            part = kwargs.get("part", 0)
            total = kwargs.get("total", 1)
            if isinstance(data, dict):
                part = data.get("part", data.get("numerator", part))
                total = data.get("total", data.get("denominator", total))
            # Also handle two numeric inputs
            if isinstance(data, (int, float)) and kwargs.get("total"):
                part = data
                total = kwargs["total"]
            return round((float(part) / float(total) * 100), 2) if total else 0
        
        elif operation == "identity":
            # Return data unchanged
            return data
        
        elif operation == "logical_or":
            # Return first truthy value or default
            default = kwargs.get("default", None)
            if isinstance(data, list):
                for item in data:
                    if item:
                        return item
                return default
            return data if data else default
        
        elif operation == "ternary_status":
            # Convert boolean/value to status string
            true_val = kwargs.get("true_value", "Yes")
            false_val = kwargs.get("false_value", "No")
            return true_val if data else false_val
        
        # === String Operations ===
        elif operation == "lowercase":
            return str(data).lower()
        
        elif operation == "uppercase":
            return str(data).upper()
        
        elif operation == "strip":
            return str(data).strip()
        
        elif operation == "split":
            delimiter = kwargs.get("delimiter", None)
            return str(data).split(delimiter)
        
        elif operation == "clean_html":
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(str(data), "lxml")
            return soup.get_text(separator=" ", strip=True)
        
        elif operation == "parse_xml":
            if isinstance(data, str):
                return ET.fromstring(data)
            return data
        
        elif operation == "extract_language_codes":
            # Extract language codes from hreflang values like "en", "en-US", "x-default"
            if isinstance(data, list):
                codes = []
                for val in data:
                    val_str = str(val).strip()
                    if val_str:
                        # Extract the primary language code (before region)
                        lang = val_str.split("-")[0].lower() if "-" in val_str else val_str.lower()
                        codes.append(lang)
                return list(set(codes))
            elif isinstance(data, str):
                return [data.split("-")[0].lower()] if data else []
            return []
        
        else:
            logger.warning(f"Unknown operation: {operation}")
            return data
    
    except Exception as e:
        logger.error(f"TRANSFORM error ({operation}): {e}")
        return data