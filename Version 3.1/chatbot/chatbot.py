import streamlit as st
import logging
from typing import Dict, Any, Optional, List

from graph.state import AuditMap
from agents.query_resolver import QueryResolver


logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')
def chatbot_page():
    st.title("SEO Chatbot 🤖")
    st.write("Ask about SEO basics or deep-dive into your current audit data.")

    if 'audit_map' not in st.session_state:
        st.session_state.audit_map = AuditMap()

    if 'query_resolver' not in st.session_state:
        st.session_state.query_resolver = QueryResolver()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("How is my meta title for example.com?"):
        st.chat_message("user").markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.spinner("Analyzing audit data..."):
            try:
                result = st.session_state.query_resolver.resolve(
                    user_query=prompt,
                    audit_map=st.session_state.audit_map,
                    chat_history=st.session_state.messages[:-1]
                )
                
                response = result.get("chatbot_response", "I couldn't process that.")
                
                with st.chat_message("assistant"):
                    st.markdown(response)
                
                st.session_state.messages.append({"role": "assistant", "content": response})

                if result["llm_decision"].get("action") == "START_AUDIT":
                    st.info("Audit triggered! Switch to the Dashboard to see real-time progress.")

            except Exception as e:
                logging.exception("UI Resolution Error")
                st.error(f"Error: {e}")
