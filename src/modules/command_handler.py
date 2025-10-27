import logging
from typing import Optional
from enum import IntEnum

from . import uart
from . import flash_interface

# Configure module logger
logger = logging.getLogger(__name__)


# Commands that SBC can receive
class Commands(IntEnum):
    """Enumeration of available commands."""

    POWEROFF = 0x30  # ASCII '0'
    REBOOT = 0x31  # ASCII '1'
    STATUS = 0x32  # ASCII '2'
    # Add more commands here as needed


# Commands that SBC can send
class PICCommands(IntEnum):
    """Enumeration of commands the Raspberry Pi can SEND to the PIC."""

    SET_LED_STATE = 0x40
    GET_PIC_STATUS = 0x41
    RESET_PIC_COUNTER = 0x42
    # Add more commands here as needed


# --- Command Handler Functions ---


def handle_poweroff(flash: Optional[flash_interface.FlashMemory] = None) -> str:
    """
    Handle poweroff command - gracefully shutdown and power off the system.

    Returns:
        Status message

    Raises:
        ShutdownRequested: To trigger graceful application shutdown
    """
    logger.warning("POWEROFF command received - initiating graceful shutdown")

    # Send acknowledgment via UART before shutting down
    try:
        response = "ACK: Powering off...\n".encode("utf-8")
        uart.send_data(response)
    except Exception as e:
        logger.error(f"Failed to send poweroff acknowledgment: {e}")

    # Raise exception to trigger graceful shutdown
    raise uart.ShutdownRequested("System poweroff requested via UART")


def handle_reboot(flash: Optional[flash_interface.FlashMemory] = None) -> str:
    """
    Handle reboot command - gracefully shutdown and reboot the system.

    Returns:
        Status message

    Raises:
        ShutdownRequested: To trigger graceful application shutdown
    """
    logger.warning("REBOOT command received - initiating graceful reboot")

    # Send acknowledgment via UART
    try:
        response = "ACK: Rebooting...\n".encode("utf-8")
        uart.send_data(response)
    except Exception as e:
        logger.error(f"Failed to send reboot acknowledgment: {e}")

    raise uart.ShutdownRequested("System reboot requested via UART")


def handle_status(flash: Optional[flash_interface.FlashMemory] = None) -> str:
    """
    Handle status command - report system status.

    Args:
        flash: Optional FlashMemory instance for status check

    Returns:
        Status message
    """
    logger.info("STATUS command received - reporting system status")

    status_parts = [
        "STATUS:",
        f"UART: {'OK' if uart.is_running() else 'STOPPED'}",
        f"Flash: {'OK' if flash and flash.is_open else 'N/A'}",
        f"Queue: {uart.get_queue_size()} msgs",
    ]

    status_msg = " | ".join(status_parts)
    logger.info(status_msg)

    # Send status via UART
    try:
        response = f"{status_msg}\n".encode("utf-8")
        uart.send_data(response)
    except Exception as e:
        logger.error(f"Failed to send status response: {e}")

    return status_msg


# Command mapping: command number -> (description, handler function)
COMMAND_MAP = {
    Commands.POWEROFF: ("Graceful system poweroff", handle_poweroff),
    Commands.REBOOT: ("Graceful system reboot", handle_reboot),
    Commands.STATUS: ("Report system status", handle_status),
    # Add more commands here:
    # Commands.CAPTURE_IMAGE: ("Capture and store image", handle_capture_image),
    # Commands.ERASE_FLASH: ("Erase flash memory", handle_erase_flash),
}


def execute_command(
    command: int, flash: Optional[flash_interface.FlashMemory] = None
) -> str:
    """
    Execute a command and return the result.

    Args:
        command: Command number to execute
        flash: Optional FlashMemory instance for commands that need it

    Returns:
        Result string for the command

    Raises:
        ShutdownRequested: If command requests system shutdown
    """
    if command not in COMMAND_MAP:
        result = f"Invalid command: {command}"
        logger.warning(result)
        return result

    description, handler = COMMAND_MAP[command]
    logger.info(f"Executing command {command}: {description}")

    try:
        # Call the handler function, passing the flash instance
        result = handler(flash)

        return result

    except uart.ShutdownRequested:
        # Re-raise shutdown requests to be handled at a higher level
        raise
    except Exception as e:
        error_msg = f"Error executing command {command}: {e}"
        logger.error(error_msg, exc_info=True)
        return error_msg


def log_available_commands():
    logger.info("Available commands:")
    for cmd_num, (description, _) in COMMAND_MAP.items():
        logger.info(f"  {cmd_num}: {description}")
