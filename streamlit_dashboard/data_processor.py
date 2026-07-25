
# Import local modules
from streamlit_dashboard.logger import get_logger
# Import Python libraries
import fastf1
import pandas as pd
import numpy as np


class DataProcessor:
    def __init__(self, config, logger):
        self.logger = logger
        self.config = config
