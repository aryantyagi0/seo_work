from typing import Dict, Any, List, Optional
import os
from openai import OpenAI

# --- OpenAI Client Setup ---
_openai_client = None

def get_openai_client():
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set.")
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client

import logging
def call_llm_completion(messages: List[Dict[str, str]], tools: Optional[List[Dict[str, Any]]] = None, response_format: Optional[Dict[str, str]] = None, **kwargs):
    """Thin transport wrapper for OpenAI chat completions."""
    client = get_openai_client()
    
    logging.info(f"[LLM Call] Model: gpt-4o-mini, Messages Count: {len(messages)}")
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            tool_choice="auto" if tools else None,
            response_format=response_format,
            **kwargs
        )
        logging.info("[LLM Call] Success")
        return response
    except Exception as e:
        logging.error(f"[LLM Call] Failed: {e}")
        raise e

def call_llm_for_chatbot_reasoning(summary_df_string: str, user_query: str) -> str:
    """
    Calls an LLM to generate a chatbot response based on the audit summary.
    """
    messages = [
        {"role": "system", "content": "You are a helpful SEO assistant. Summarize the audit results concisely and provide relevant next steps or insights."},
        {"role": "user", "content": f"Based on the following audit summary and the user's initial query, provide a concise chatbot response:\n\nUser Query: {user_query}\n\nAudit Summary:\n{summary_df_string}"}
    ]
    try:
        response = call_llm_completion(messages=messages)
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error calling LLM for chatbot reasoning: {e}")
        return "I encountered an error while trying to summarize the audit results."


