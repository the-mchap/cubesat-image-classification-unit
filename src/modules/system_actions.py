import logging
import subprocess
import sys
import time
from typing import Optional

from modules import uart
from modules import flash_interface

# Configure module logger
logger = logging.getLogger(__name__)


def perform_system_poweroff() -> None:
    """
    Perform actual system poweroff using sudo poweroff command.
    """
    logger.warning("Executing system poweroff in 2 seconds...")
    time.sleep(2)  # Brief delay to ensure logging completes

    try:
        subprocess.run(["sudo", "poweroff"], check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to execute poweroff command: {e}")
        sys.exit(1)
    except FileNotFoundError:
        logger.error("poweroff command not found")
        sys.exit(1)


def perform_system_reboot() -> None:
    """
    Perform actual system reboot using sudo reboot command.
    """
    logger.warning("Executing system reboot in 2 seconds...")
    time.sleep(2)  # Brief delay to ensure logging completes

    try:
        subprocess.run(["sudo", "reboot"], check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to execute reboot command: {e}")
        sys.exit(1)
    except FileNotFoundError:
        logger.error("reboot command not found")
        sys.exit(1)


def cleanup(flash: Optional[flash_interface.FlashMemory]) -> None:
    """
    Perform cleanup operations before shutdown.

    Args:
        flash: Optional FlashMemory instance to clean up
    """
    logger.info("Starting cleanup...")

    # Stop UART listener
    try:
        uart.stop_listener()
        logger.info("UART listener stopped")
    except Exception as e:
        logger.error(f"Error stopping UART listener: {e}")

    # Close flash memory
    if flash:
        try:
            flash.close()
            logger.info("Flash memory closed")
        except Exception as e:
            logger.error(f"Error closing flash memory: {e}")

    logger.info("Cleanup complete")