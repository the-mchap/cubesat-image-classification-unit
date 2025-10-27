import serial
import threading
import queue
import logging
from typing import Optional, Callable, Any

# Configure module logger
logger = logging.getLogger(__name__)

# --- Module-level variables ---
_serial_port: Optional[serial.Serial] = None
_listener_thread: Optional[threading.Thread] = None
_data_queue: queue.Queue = queue.Queue()
_is_running: bool = False
_lock = threading.Lock()

# --- Constants ---
DEFAULT_TIMEOUT = 1.0
THREAD_JOIN_TIMEOUT = 2.0
TEST_SLEEP_INTERVAL = 0.1


class SerialError(Exception):
    """Custom exception for serial communication errors."""

    pass


class ShutdownRequested(Exception):
    """Exception to signal graceful shutdown was requested."""

    pass


def parse_command(data: bytes) -> Optional[int]:
    """
    Parse received data into a command number.

    Args:
        data: Received bytes from UART

    Returns:
        Command number as integer, or None if parsing fails
    """
    try:
        character = data.decode("utf-8").strip()
        command = int(character)
        logger.debug(f"Parsed command: {command}")
        return command
    except (UnicodeDecodeError, ValueError) as e:
        logger.warning(f"Failed to parse command from data {data.hex()}: {e}")
        return None


def process_data(
    execute_command: Callable[[int, Optional[Any]], str], flash: Optional[Any]
) -> None:
    """
    Process all pending data in the UART queue.

    Args:
        execute_command: Function to execute a parsed command
        flash: Optional FlashMemory instance for commands that need it

    Raises:
        ShutdownRequested: If a shutdown command is processed
    """
    processed_count = 0

    while not _data_queue.empty():
        try:
            received_data = _data_queue.get_nowait()

            try:
                character = received_data.decode("utf-8")
                logger.info(f"Received: '{character}' (0x{received_data.hex()})")

                # Parse and execute command
                command = parse_command(received_data)
                if command is not None:
                    result = execute_command(command, flash)
                    logger.info(f"Result: {result}")

                processed_count += 1

            except UnicodeDecodeError:
                logger.warning(f"Received non-UTF-8 byte: 0x{received_data.hex()}")

        except ShutdownRequested:
            # Propagate shutdown request up
            raise
        except Exception as e:
            logger.error(f"Error processing UART data: {e}")
            break

    if processed_count > 0:
        logger.debug(f"Processed {processed_count} UART messages")


def _serial_listener() -> None:
    """
    Target function for the listener thread.
    Continuously listens for serial data and puts it in the queue.
    """
    global _is_running

    logger.info("Listener thread started")

    try:
        while _is_running:
            try:
                # Block until at least one byte is received
                incoming_byte = _serial_port.read(1)

                if incoming_byte and _is_running:
                    _data_queue.put(incoming_byte)
                    logger.debug(f"Received byte: {incoming_byte.hex()}")

            except serial.SerialException as e:
                if _is_running:
                    logger.error(f"Serial exception in listener: {e}")
                break
            except Exception as e:
                logger.error(f"Unexpected error in listener: {e}")
                break
    finally:
        logger.info("Listener thread finished")


def is_running() -> bool:
    """
    Check if the serial listener is currently running.

    Returns:
        True if listener is running, False otherwise
    """
    return _is_running


def start_listener(
    port: str, baud_rate: int, timeout: float = DEFAULT_TIMEOUT
) -> Optional[queue.Queue]:
    """
    Initialize the serial port and start the listener thread.

    Args:
        port: Serial port path (e.g., '/dev/ttyAMA0')
        baud_rate: Baud rate for serial communication
        timeout: Read timeout in seconds (default: 1.0)

    Returns:
        Queue object for reading received data, or None if initialization failed

    Raises:
        SerialError: If serial port cannot be opened or listener is already running
    """
    global _serial_port, _listener_thread, _is_running

    with _lock:
        if _is_running:
            raise SerialError(
                "Listener is already running. Stop it before starting again."
            )

        try:
            _serial_port = serial.Serial(port, baud_rate, timeout=timeout)
            logger.info(
                f"Serial port {port} opened at {baud_rate} baud "
                f"(timeout: {timeout}s)"
            )
        except serial.SerialException as e:
            error_msg = f"Could not open serial port {port}: {e}"
            logger.error(error_msg)
            raise SerialError(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error opening serial port: {e}"
            logger.error(error_msg)
            raise SerialError(error_msg)

        # Clear any existing data in the queue
        while not _data_queue.empty():
            try:
                _data_queue.get_nowait()
            except queue.Empty:
                break

        # Start the listener thread
        _is_running = True
        _listener_thread = threading.Thread(
            target=_serial_listener, daemon=True, name="SerialListener"
        )
        _listener_thread.start()

        return _data_queue


def send_data(data: bytes) -> bool:
    """
    Send bytes of data over the serial port.

    Args:
        data: Bytes to send

    Returns:
        True if data was sent successfully, False otherwise

    Raises:
        SerialError: If serial port is not open
    """
    if not _serial_port or not _serial_port.is_open:
        raise SerialError("Cannot send data, serial port is not open")

    try:
        bytes_written = _serial_port.write(data)
        logger.debug(f"Sent {bytes_written} bytes: {data.hex()}")
        return bytes_written == len(data)
    except serial.SerialException as e:
        logger.error(f"Error sending data: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending data: {e}")
        return False


def get_data(timeout: Optional[float] = None) -> Optional[bytes]:
    """
    Get data from the queue (non-blocking by default).

    Args:
        timeout: Maximum time to wait for data in seconds (None = no wait)

    Returns:
        Received data bytes, or None if queue is empty
    """
    try:
        if timeout is None:
            return _data_queue.get_nowait()
        else:
            return _data_queue.get(timeout=timeout)
    except queue.Empty:
        return None


def clear_queue() -> int:
    """
    Clear all pending data from the receive queue.

    Returns:
        Number of items removed from the queue
    """
    count = 0
    while not _data_queue.empty():
        try:
            _data_queue.get_nowait()
            count += 1
        except queue.Empty:
            break

    if count > 0:
        logger.debug(f"Cleared {count} items from receive queue")

    return count


def stop_listener() -> None:
    """
    Stop the listener thread and close the serial port.
    This function is idempotent and safe to call multiple times.
    """
    global _is_running, _serial_port, _listener_thread

    with _lock:
        if not _is_running and not _serial_port:
            logger.debug("Listener already stopped")
            return

        logger.info("Stopping serial listener...")
        _is_running = False

        # Wait for listener thread to finish
        if _listener_thread and _listener_thread.is_alive():
            logger.debug("Waiting for listener thread to finish...")
            _listener_thread.join(timeout=THREAD_JOIN_TIMEOUT)

            if _listener_thread.is_alive():
                logger.warning("Listener thread did not finish in time")

        # Close serial port
        if _serial_port and _serial_port.is_open:
            try:
                _serial_port.close()
                logger.info("Serial port closed")
            except Exception as e:
                logger.error(f"Error closing serial port: {e}")

        _serial_port = None
        _listener_thread = None


def get_queue_size() -> int:
    """
    Get the current number of items in the receive queue.

    Returns:
        Number of items in the queue
    """
    return _data_queue.qsize()
