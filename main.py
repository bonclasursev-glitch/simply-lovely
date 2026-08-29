# Import local modules
from streamlit_dashboard.logger import get_logger
from streamlit_dashboard.dashboard_orchestrator import DashboardOrchestrator
from streamlit_dashboard.data_processor import DataProcessor
from streamlit_dashboard.layout_manager import LayoutManager
from streamlit_dashboard.visualizer import Visualizer

# Import Python libraries
from pathlib import Path
import tomllib

def run():
    logger = get_logger(__name__)
    logger.info("Exiting the pit lane!")
    logger.info("Loading config files")
    config_path = Path(__file__).resolve().parent / 'config' / 'config.toml'
    with config_path.open('rb') as config_file:
        config = tomllib.load(config_file)
    logger.info("Initialising Data Processor")
    data_processor = DataProcessor(config, logger)
    logger.info("Initialising Visualizer")
    visualizer = Visualizer(config)
    logger.info("Initialising Layout Manager")
    layout_manager = LayoutManager(config, visualizer)
    logger.info("Initialising Dashboard Orchestrator")
    dashboard_orchestrator = DashboardOrchestrator(config, data_processor, layout_manager)
    logger.info("And it's lights out and away we go!")
    dashboard_orchestrator.run_dashboard()

if __name__ == '__main__':
    run()