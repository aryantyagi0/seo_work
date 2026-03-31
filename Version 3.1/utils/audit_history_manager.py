import json
import os
from typing import List, Dict, Any, Optional

from graph.state import AuditMap, PageAuditState, AuditParameterState # Import necessary dataclasses

AUDIT_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'kb', 'audit_history.json')

def load_audit_history() -> List[AuditMap]:
    """
    Loads all AuditMap objects from kb/audit_history.json.
    Returns a list of AuditMap objects.
    """
    if not os.path.exists(AUDIT_HISTORY_FILE):
        return []

    try:
        with open(AUDIT_HISTORY_FILE, 'r') as f:
            data = json.load(f)
            # Deserialize each dict back into an AuditMap object
            return [AuditMap.from_dict(item) for item in data]
    except json.JSONDecodeError:
        print(f"Warning: {AUDIT_HISTORY_FILE} is corrupted or empty. Starting with empty history.")
        return []
    except Exception as e:
        print(f"Error loading audit history from {AUDIT_HISTORY_FILE}: {e}")
        return []

def save_audit_history(audit_map_to_save: AuditMap):
    """
    Saves a new AuditMap object to kb/audit_history.json.
    It appends the new audit map to the existing history.
    """
    # Load existing history
    history = load_audit_history()

    # Convert the new audit_map to a dictionary for serialization
    audit_map_dict = audit_map_to_save.to_dict()

    # Append new audit map (or update if an audit for the same main URL already exists in history)
    # For simplicity, we'll append for now. More complex logic can be added later for updates.
    history.append(audit_map_to_save) # Append the actual AuditMap object
    
    # Convert the entire history (list of AuditMap objects) to a list of dictionaries
    history_dicts = [am.to_dict() for am in history]

    # Ensure the kb directory exists
    kb_dir = os.path.dirname(AUDIT_HISTORY_FILE)
    os.makedirs(kb_dir, exist_ok=True)

    try:
        with open(AUDIT_HISTORY_FILE, 'w') as f:
            json.dump(history_dicts if history_dicts else [], f, indent=4)
    except Exception as e:
        print(f"Error saving audit history to {AUDIT_HISTORY_FILE}: {e}")

def find_audit_in_history(url: str) -> Optional[AuditMap]:
    """
    Finds the latest audit for a given URL in the history.
    Returns the AuditMap if found, otherwise None.
    """
    history = load_audit_history()
    # Assuming the most recent audit for a URL is the one we want.
    # We can iterate in reverse if history is always appended.
    for audit_map in reversed(history):
        if url in audit_map.pages:
            # Create a new AuditMap containing only the requested URL's data
            # This prevents loading potentially large unrelated audit data if only one URL is needed
            single_page_audit_map = AuditMap()
            single_page_audit_map.pages[url] = audit_map.pages[url]
            return single_page_audit_map
    return None

