import logging
from typing import Optional

from modules import uart
from modules import flash_interface
from modules import config

# Configure module logger
logger = logging.getLogger(__name__)


class ApplicationError(Exception):
    """Custom exception for application errors."""

    pass


def initialize_flash() -> Optional[flash_interface.FlashMemory]:
    """
    Initialize the flash memory interface.

    Returns:
        FlashMemory instance if successful, None otherwise
    """
    try:
        flash = flash_interface.FlashMemory(
            bus=config.SPI_BUS, device=config.SPI_DEVICE
        )

        if flash.is_open:
            logger.info("Flash memory initialized successfully")
            return flash
        else:
            logger.warning("Flash memory opened but is_open flag is False")
            return None

    except flash_interface.FlashMemoryError as e:
        logger.error(f"Failed to initialize flash memory: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error initializing flash memory: {e}")
        return None


def initialize_uart() -> Optional:
    """
    Initialize the UART listener.

    Returns:
        UART queue for receiving data, or None if initialization failed

    Raises:
        ApplicationError: If UART initialization fails
    """
    try:
        uart_queue = uart.start_listener(config.UART_PORT, config.BAUD_RATE)

        if not uart_queue:
            raise ApplicationError("Failed to start UART listener")

        logger.info("UART listener started successfully")
        return uart_queue

    except uart.SerialError as e:
        logger.error(f"UART initialization failed: {e}")
        raise ApplicationError(f"UART initialization failed: {e}")
