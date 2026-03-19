"""
Writer Agent - LLM Brain 2: The Reporter
Converts raw metrics into professional SEO summaries
"""
import yaml
import json
from pathlib import Path
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from config.settings import OPENAI_API_KEY, WRITER_MODEL, LLM_TEMPERATURE, LLM_TIMEOUT, PROMPTS_DIR
from utils.logging_config import get_logger

logger = get_logger("WriterAgent")


class WriterAgent:
    def __init__(self):
        # Load writer prompt from YAML file
        prompt_path = PROMPTS_DIR / "writer.yaml"
        with open(prompt_path, 'r') as f:
            self.prompt_config = yaml.safe_load(f)
        
        self.llm = ChatOpenAI(
            model_name=WRITER_MODEL,
            openai_api_key=OPENAI_API_KEY,
            temperature=LLM_TEMPERATURE,
            timeout=LLM_TIMEOUT
        )
        
        logger.info("Writer Agent initialized")
    
    def _build_system_prompt(self) -> str:
        """Build system prompt from YAML configuration"""
        config = self.prompt_config
        
        prompt = f"**Role:** {config['role']}\n\n"
        prompt += f"**Mission:** {config['mission']}\n\n"
        
        prompt += "**Synthesis Logic:**\n"
        prompt += f"- Tone: {config['synthesis_logic']['tone']}\n"
        prompt += f"- Structure:\n"
        for key, val in config['synthesis_logic']['structure'].items():
            prompt += f"  - {key}: {val}\n"
        
        prompt += "\n**Column-Specific Guidance:**\n"
        for key, val in config['column_specific_guidance'].items():
            prompt += f"- {key}: {val}\n"
        
        prompt += f"\n**Output Requirements:**\n"
        prompt += f"- Format: {config['output_requirement']['format']}\n"
        prompt += f"- Max Length: {config['output_requirement']['max_length']} characters\n"
        
        return prompt
    
    async def generate_summary(self, column_name: str, raw_metrics: Dict[str, Any], url: str) -> str:
        """Generate professional summary from raw metrics data"""
        logger.info(f"Writing summary for: {column_name}")
        
        system_prompt = self._build_system_prompt()
        
        # Limit metrics data to prevent token overflow
        metrics_str = json.dumps(raw_metrics, indent=2, default=str)
        if len(metrics_str) > 3000:
            metrics_str = metrics_str[:3000] + "\n... [truncated for brevity]"
        
        user_prompt = f"""
**URL:** {url}
**Column:** {column_name}
**Raw Metrics:**
{metrics_str}

**Task:** Write a concise, TECHNICAL SEO summary that:
1. States SPECIFIC findings with exact metrics from the raw data (e.g., exact word count, character count, number of broken links, SSL expiry date, URL count, status codes, tag names, specific URLs)
2. Explains the SEO significance of these specific findings
3. Provides concrete, actionable recommendations with specific details

**CRITICAL RULES:**
- You MUST include specific numbers, counts, and values from the raw metrics. Never say "some" or "several" when a count is available.
- If broken links found, state whether internal/external, HTTP status codes, and sample URLs.
- If the column is about 404 and raw metrics show is_404=true, include a "Recommended update" sentence.
- If raw metrics include suggested_similar_urls, explicitly list those URLs as likely intended alternatives for typo URLs.
- If word count available, state the exact count and threshold comparison.
- If SSL data available, state TLS version, expiry days, redirect status.
- If meta title/description found, state the exact text and character count.
- If sitemap data available, state URL count and inclusion status.
- Keep it technical and data-driven. No filler sentences.
- Plain text only, no markdown, no bullet points.
- Target ~500 characters. Expand only if the data warrants more detail.
"""
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = await self.llm.ainvoke(messages)
            summary = response.content.strip()
            logger.info(f"Summary generated for {column_name} ({len(summary)} chars)")
            return summary
        
        except Exception as e:
            logger.error(f"Writer error for {column_name}: {e}")
            return f"Error generating summary: {str(e)}"