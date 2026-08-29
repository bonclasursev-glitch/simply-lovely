# Import local modules
from streamlit_dashboard.logger import get_logger
# Import Python libraries
import plotly.graph_objs as go
from plotly.subplots import make_subplots


class LayoutManager:
    def __init__(self, logger):
        self.logger = logger