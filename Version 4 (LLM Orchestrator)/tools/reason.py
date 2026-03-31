"""
REASON Primitive: LLM-based subjective analysis
"""
import json
from typing import Any, Dict
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from config.settings import OPENAI_API_KEY, PLANNER_MODEL, LLM_TEMPERATURE
from utils.logging_config import get_logger

logger = get_logger("REASON")

# Reuse a single LLM instance instead of creating one per call
_reason_llm = None


def _get_reason_llm():
    global _reason_llm
    if _reason_llm is None:
        _reason_llm = ChatOpenAI(
            model_name=PLANNER_MODEL,
            openai_api_key=OPENAI_API_KEY,
            temperature=LLM_TEMPERATURE,
            timeout=45,
        )
    return _reason_llm


async def reason(context: Any, question: str) -> Dict[str, Any]:
    """
    Use LLM to perform subjective analysis on data
    
    Args:
        context: Any data structure (will be JSON serialized)
        question: Natural language question for the LLM
    
    Returns:
        {"answer": str, "confidence": float, "explanation": str}
    """
    try:
        llm = _get_reason_llm()
        
        # Limit context size to prevent token overflow
        context_str = json.dumps(context, indent=2, default=str)
        if len(context_str) > 8000:
            context_str = context_str[:8000] + "\n... [truncated]"
        
        system_prompt = """You are an expert SEO analyst. Answer the question based on the provided context.
Provide:
1. A direct answer
2. Your confidence level (0-100)
3. A brief explanation

Return JSON format: {"answer": "...", "confidence": 85, "explanation": "..."}"""
        
        user_prompt = f"""**Context:**
{context_str}

**Question:**
{question}
"""
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = await llm.ainvoke(messages)
        
        # Parse response as JSON
        try:
            result = json.loads(response.content)
        except:
            result = {
                "answer": response.content,
                "confidence": 50,
                "explanation": "Raw LLM response"
            }
        
        logger.info(f"REASON: {question[:50]}... → {result.get('confidence', 0)}% confidence")
        return result
    
    except Exception as e:
        logger.error(f"REASON error: {e}")
        return {
            "answer": "Error",
            "confidence": 0,
            "explanation": str(e)
        }