import os
from logging.handlers import RotatingFileHandler

class MakeDirRotatingFileHandler(RotatingFileHandler):
    """
    A RotatingFileHandler that creates the log directory if it does not exist.
    """
    def __init__(self, filename, *args, **kwargs):
        # Get the directory part of the filename
        log_dir = os.path.dirname(filename)
        
        # Create the directory if it doesn't exist
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        # Initialize the parent class
        super().__init__(filename, *args, **kwargs)