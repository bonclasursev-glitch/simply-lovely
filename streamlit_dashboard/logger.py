import logging
import os
from datetime import datetime

# create directory for dev logs & format logs
logs_directory = "logs"
os.makedirs(logs_directory, exist_ok = True)
logs_format = "%(datetime)s - %(name)s - %(threadname)s - %(levelName)s - %(message)s"
datetime_now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
log_filename = os.path.join(logs_directory, f"SimplyLovely_{datetime_now}.log")

def get_logger(module_name):
    # Create logger witht he appropriate name
    logger = logging.getLogger(module_name)
    logger.setLevel(logging.DEBUG)

    # Avoid duplication of handlers
    if not logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        file_handler = logging.FileHandler(log_filename)
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(logs_format)
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    return logger