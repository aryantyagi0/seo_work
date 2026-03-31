"""
Centralized logging configuration
"""
import logging
from config.settings import LOG_LEVEL, LOG_FORMAT


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger instance"""
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        logger.setLevel(getattr(logging, LOG_LEVEL))
        
        handler = logging.StreamHandler()
        handler.setLevel(getattr(logging, LOG_LEVEL))
        
        formatter = logging.Formatter(LOG_FORMAT)
        handler.setFormatter(formatter)
        
        logger.addHandler(handler)
    
    return logger