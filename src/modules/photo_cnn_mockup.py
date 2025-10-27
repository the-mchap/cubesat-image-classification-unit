import os
import random
import logging
from pathlib import Path
from typing import Optional, Tuple

# Configure module logger
logger = logging.getLogger(__name__)

# --- Constants ---
MOCK_IMAGE_DIR = str(Path(__file__).parent.joinpath("mock_images"))
CLASSIFICATIONS = ["Forests", "Plains", "Sky"]
VALID_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


def simulate_image_capture(base_dir: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Randomly select an image from mock directories to simulate capture and classification.

    Args:
        base_dir: Base directory containing classification subdirectories

    Returns:
        Tuple of (classification_string, image_file_path) or (None, None) if error
    """
    try:
        base_path = Path(base_dir)

        if not base_path.exists():
            logger.error(
                f"Mock image directory not found at '{base_dir}'. "
                f"Please create: {base_dir}/[Forests|Plains|Sky]"
            )
            return None, None

        # Randomly choose a classification
        chosen_class = random.choice(CLASSIFICATIONS)
        class_dir = base_path / chosen_class

        if not class_dir.exists():
            logger.error(f"Classification directory not found: {class_dir}")
            return None, None

        # Get all valid images from the classification folder
        images = [
            f
            for f in os.listdir(class_dir)
            if f.lower().endswith(VALID_IMAGE_EXTENSIONS)
        ]

        if not images:
            logger.warning(f"No images found in {class_dir}")
            return None, None

        # Randomly select an image
        chosen_image_name = random.choice(images)
        full_path = str(class_dir / chosen_image_name)

        logger.info(
            f"Simulated capture: Classified as '{chosen_class}', "
            f"image: '{chosen_image_name}'"
        )
        return chosen_class, full_path

    except Exception as e:
        logger.error(f"Error during image capture simulation: {e}")
        return None, None
