"""
Logging configuration for Tidal DL CLI
"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler


def setup_logger(
    name: str = "tidal_dl",
    log_dir: Path = None,
    level: int = logging.DEBUG
) -> logging.Logger:
    """
    Setup application logger with separate files for main and debug logs.
    
    Creates two log files:
    - tidal.log: INFO level and above (main operational logs)
    - tidal-debug.log: DEBUG level (detailed debugging info)
    
    Args:
        name: Logger name
        log_dir: Directory for log files
        level: Logging level for the logger
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Check if handlers already exist to avoid duplicates
    if logger.handlers:
        return logger
    
    # Formatters
    main_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    debug_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # Main log file - INFO and above
        main_log_path = log_dir / "tidal.log"
        main_handler = RotatingFileHandler(
            main_log_path,
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3,
            encoding='utf-8'
        )
        main_handler.setFormatter(main_formatter)
        main_handler.setLevel(logging.INFO)
        logger.addHandler(main_handler)
        
        # Debug log file - DEBUG and above (everything)
        debug_log_path = log_dir / "tidal-debug.log"
        debug_handler = RotatingFileHandler(
            debug_log_path,
            maxBytes=10*1024*1024,  # 10MB (debug logs are larger)
            backupCount=2,
            encoding='utf-8'
        )
        debug_handler.setFormatter(debug_formatter)
        debug_handler.setLevel(logging.DEBUG)
        logger.addHandler(debug_handler)
    
    return logger


# Create global logger instance
log_dir = Path("logs")
logger = setup_logger("tidal_dl", log_dir)
