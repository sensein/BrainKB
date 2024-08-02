import json
import logging
from datetime import datetime
from logging import Formatter

LOGGING_FILE_PATH = 'examples.log'


class JsonFormatter(Formatter):
    def __init__(self):
        super(JsonFormatter, self).__init__()

    def formatTime(self, record):
        # Use datetime to format timestamp in ISO 8601 format
        dt = datetime.fromtimestamp(record.created)
        return dt.isoformat()
    
    def format(self, record):
        json_record = {
            'timestamp': self.formatTime(record),
            'level': record.levelname,
            'message': record.getMessage(),
        }
        return json.dumps(json_record)


def get_logger(name):
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.FileHandler(LOGGING_FILE_PATH)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)

    logger.setLevel(logging.DEBUG)
    return logger