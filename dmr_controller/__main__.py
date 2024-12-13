import logging
import sys
from .ui import ControllerUI
from pathlib import Path
from PyQt6.QtWidgets import QApplication

def setup_logging():
    """Configure logging for the application."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('dmr_controller.log')
        ]
    )

def main():
    """Main entry point for the application."""
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Create downloads directory if it doesn't exist
    downloads_dir = Path('downloads')
    downloads_dir.mkdir(exist_ok=True)
    
    try:
        logger.info("Starting DMR Controller")
        app = QApplication(sys.argv)
        controller_ui = ControllerUI()
        controller_ui.run()
        sys.exit(app.exec())
    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
