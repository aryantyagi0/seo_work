import requests
import logging
import asyncio
import xml.etree.ElementTree as ET
from langchain_core.tools import tool

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@tool
async def extract_urls_from_sitemap_tool(sitemap_url: str) -> list[str]:
    """
    Fetches and parses an XML sitemap to extract URLs.
    
    Args:
        sitemap_url: The URL of the sitemap XML file.
        
    Returns:
        A list of URLs found in the sitemap, or an empty list if an error occurs.
    """
    try:
        response = await asyncio.to_thread(
            requests.get,
            sitemap_url,
            timeout=10
        )
        response.raise_for_status()
        
        root = ET.fromstring(response.content)
        
        # Namespace for sitemap elements
        namespace = {'sitemap': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        
        urls = []
        for url_element in root.findall('sitemap:url', namespace):
            loc = url_element.find('sitemap:loc', namespace)
            if loc is not None:
                urls.append(loc.text)
        
        return urls
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching sitemap from {sitemap_url}: {e}")
        return []
    except ET.ParseError as e:
        logging.error(f"Error parsing sitemap XML from {sitemap_url}: {e}")
        return []
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        return []

