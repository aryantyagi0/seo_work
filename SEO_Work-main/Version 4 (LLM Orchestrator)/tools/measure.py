"""
MEASURE Primitive: Count, calculate length, frequency, keyword density, URL depth
"""
import re
from typing import Any, Union, List, Dict
from urllib.parse import urlparse
from bs4 import Tag
from utils.logging_config import get_logger

logger = get_logger("MEASURE")

# English stopwords for keyword density analysis
ENGLISH_STOPWORDS = set("""
a about above after again against all am an and any are aren't as at be because been before being below between both but by
can't cannot could couldn't did didn't do does doesn't doing don't down during each few for from further had hadn't has hasn't have haven't having he he'd he'll he's her here here's hers herself him himself his how how's i i'd i'll i'm i've if in into is isn't it it's its itself let's me more most mustn't my myself no nor not of off on once only or other ought our ours ourselves out over own same shan't she she'd she'll she's should shouldn't so some such than that that's the their theirs them themselves then there there's these they they'd they'll they're they've this those through to too under until up very was wasn't we we'd we'll we're we've were weren't what what's when when's where where's which while who who's whom why why's with won't would wouldn't you you'd you'll you're you've your yours yourself yourselves
""".split())


async def measure(data: Any, metric: str) -> Union[int, float, Dict]:
    """
    Measure data
    
    Args:
        data: String, list, or collection
        metric: "length", "count", "word_count", "frequency",
                "keyword_density", "url_depth"
    
    Returns:
        Numeric value or dict (for frequency/keyword_density)
    """
    try:
        if metric == "length":
            # Calculate length of string or collection
            if isinstance(data, str):
                return len(data)
            elif isinstance(data, (list, tuple, set)):
                return len(data)
            else:
                return 0
        
        elif metric == "count":
            if isinstance(data, (list, tuple, set)):
                return len(data)
            elif data is None:
                return 0
            else:
                return 1
        
        elif metric == "word_count":
            # Count words in text, extract from HTML if needed
            if isinstance(data, str):
                text = data
                # Extract main content from HTML if applicable
                if "<" in text and ">" in text:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(text, "lxml")
                    # Try to find main content container
                    main_el = None
                    for sel in ["main", "article", "[role='main']", "#content", ".content",
                                "#main-content", ".main-content", ".post-content", ".entry-content"]:
                        main_el = soup.select_one(sel)
                        if main_el:
                            break
                    target = main_el if main_el else soup
                    # Remove script, style, and other non-content tags
                    for tag in target(["script", "style", "noscript", "svg", "meta", "link",
                                       "nav", "footer", "header", "aside"]):
                        tag.decompose()
                    text = target.get_text(separator=" ", strip=True)
                words = re.findall(r"\b[a-zA-Z]{2,}\b", text)
                return len(words)
            elif isinstance(data, Tag):
                text = data.get_text(separator=" ", strip=True)
                words = re.findall(r"\b[a-zA-Z]{2,}\b", text)
                return len(words)
            return 0
        
        elif metric == "frequency":
            if isinstance(data, str):
                words = data.lower().split()
                freq = {}
                for word in words:
                    freq[word] = freq.get(word, 0) + 1
                return freq
            return {}

        elif metric == "url_depth":
            # Calculate depth of URL path
            url_str = str(data) if data else ""
            path = urlparse(url_str).path.strip("/")
            return 0 if not path else len(path.split("/"))

        elif metric == "keyword_density":
            # Calculate TF-IDF keyword density
            return _keyword_density(data)
        
        else:
            logger.warning(f"Unknown metric: {metric}")
            return 0
    
    except Exception as e:
        logger.error(f"MEASURE error: {e}")
        return 0


def _keyword_density(data: Any) -> Dict:
    """Calculate TF-IDF based keyword density with single, bigram, and trigram analysis"""
    text = ""
    if isinstance(data, str):
        # Strip HTML tags if present
        if "<" in data and ">" in data:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(data, "lxml")
            # Remove non-content elements
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
        else:
            text = data
    else:
        text = str(data) if data else ""

    if not text or not text.strip():
        return {"status": "No", "total_words": 0, "top_single_words": [], "top_bigrams": [], "top_trigrams": []}

    content_text = text.lower()
    words = re.findall(r"\b[a-z]{3,}\b", content_text)
    total_words = len(words) if words else 1

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 3))
        tfidf_matrix = vectorizer.fit_transform([content_text])
        feature_names = vectorizer.get_feature_names_out()

        if len(feature_names) == 0:
            return {"status": "No", "total_words": total_words, "top_single_words": [], "top_bigrams": [], "top_trigrams": []}

        scores = tfidf_matrix.toarray()[0]
        ranked_idx = scores.argsort()[::-1]

        grouped = {1: [], 2: [], 3: []}
        seen = set()

        for idx in ranked_idx:
            fname = feature_names[idx]
            if fname in seen:
                continue
            if " " in fname:
                count = content_text.count(fname)
            else:
                count = sum(1 for w in words if w == fname)
            density = (count / total_words) * 100
            n = fname.count(" ") + 1
            if n > 3:
                continue
            if len(grouped.get(n, [])) < 5:
                grouped.setdefault(n, []).append((fname, round(density, 2)))
                seen.add(fname)
            if all(len(grouped.get(g, [])) >= 5 for g in (1, 2, 3)):
                break

        return {
            "status": "Yes",
            "total_words": total_words,
            "top_single_words": grouped.get(1, []),
            "top_bigrams": grouped.get(2, []),
            "top_trigrams": grouped.get(3, []),
        }

    except ImportError:
        # Fallback without sklearn
        freq = {}
        for word in words:
            if word not in ENGLISH_STOPWORDS:
                freq[word] = freq.get(word, 0) + 1
        top = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:10]
        top_kw = [(w, round((c / total_words) * 100, 2)) for w, c in top]
        return {
            "status": "Yes" if top_kw else "No",
            "total_words": total_words,
            "top_single_words": top_kw,
            "top_bigrams": [],
            "top_trigrams": [],
        }
    except Exception:
        return {"status": "No", "total_words": total_words, "top_single_words": [], "top_bigrams": [], "top_trigrams": []}