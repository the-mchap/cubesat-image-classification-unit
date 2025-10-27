from enum import Enum
import logging
import time

from . import crc_16
from . import uart
from . import config
from . import command_handler

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- Constants and Enums ---


class UARTError(Enum):
    """Enumeration of UART communication errors."""

    NO_ERROR = 0
    BAD_FRAME = 1
    INVALID_CHECKSUM = 2
    MAX_ERRORS = 3


class FrameType(Enum):
    """Enumeration of received frame types."""

    COMMAND = 0
    ACK = 1
    NACK_FORMAT = 2
    NACK_CHECKSUM = 3


# --- Frame Constants ---
NACK_INVALID_FIELD_VALUE = 0xFF
ACK_NACK_DATA_LENGTH = 0x00

MAXIMUM_BUFFER_SIZE = 45
MINIMUM_BUFFER_SIZE = 6
FRAME_OVERHEAD = 6  # HEADER, CMD, LEN, CRC_MSB, CRC_LSB, STOP_BYTE
HEADER = 0x3E
STOP_BYTE = 0x0A

HEADER_IDX = 0
CMD_IDX = 1
DATA_LENGTH_IDX = 2
CRC_MSB_IDX_OFFSET = 3
CRC_LSB_IDX_OFFSET = 4


class UARTProtocol:
    def __init__(self):
        self.buffer = bytearray()

    def pull_frame(self) -> None:
        """
        Pulls a maximum of 45 bytes of data (if any) from the uart queue into the
        internal buffer to be processed.
        """
        for _ in range(MAXIMUM_BUFFER_SIZE):
            data = uart.get_data()
            if data is None:
                break
            self.buffer.extend(data)

    def validate_and_extract_frame(self) -> bytes | None:
        """
        Validates the internal buffer for a single, complete, valid frame.

        This function attempts a 'one-shot' parse of the data at the start of
        the buffer. If the frame is structurally malformed (bad header, bad
        stop byte), the buffer is cleared.

        Returns:
            A bytes object containing a valid frame, or None if no complete
            or valid frame can be parsed.
        """
        # A frame must have a minimum size and start with the HEADER
        if len(self.buffer) < MINIMUM_BUFFER_SIZE or self.buffer[HEADER_IDX] != HEADER:
            if self.buffer:
                logging.warning(
                    f"Invalid header or too short. Discarding buffer: {self.buffer.hex()}"
                )
                nack_frame = self.nack(UARTError.BAD_FRAME)
                if uart.send_data(nack_frame):
                    logging.warning("Sent NACK to PIC (Bad frame)")
                else:
                    logging.error("Failed to send NACK")
                self.buffer.clear()
            return None

        # Determine the expected full length from the payload length byte
        expected_length = self.buffer[DATA_LENGTH_IDX] + FRAME_OVERHEAD

        # The buffer must contain the complete frame
        if len(self.buffer) < expected_length:
            return None  # Frame is still arriving, wait for more data

        # The byte at the end of the expected frame must be the stop byte
        if self.buffer[expected_length - 1] != STOP_BYTE:
            logging.warning(
                f"Invalid stop byte. Discarding buffer: {self.buffer.hex()}"
            )
            nack_frame = self.nack(UARTError.BAD_FRAME)
                if uart.send_data(nack_frame):
                    logging.warning("Sent NACK to PIC (Bad frame)")
                else:
                    logging.error("Failed to send NACK")
            self.buffer.clear()
            return None

        # All structural checks passed. Extract the frame and update the buffer.
        valid_frame = bytes(self.buffer[:expected_length])
        self.buffer = self.buffer[expected_length:]
        return valid_frame

    def classify_frame(self, frame: bytes) -> FrameType:
        """
        Classifies a structurally valid frame.

        Args:
            frame: A structurally valid data frame.

        Returns:
            The FrameType classification.
        """
        # Frames with payload are always commands
        if len(frame) > MINIMUM_BUFFER_SIZE:
            return FrameType.COMMAND

        # 6-byte frames need further classification
        # Check for specific, constant NACK patterns first
        if frame == bytes([0x3E, 0xFF, 0x00, 0xFF, 0xFF, 0x0A]):
            return FrameType.NACK_CHECKSUM
        if frame == bytes([0x3E, 0x00, 0x00, 0x00, 0x00, 0x0A]):
            return FrameType.NACK_FORMAT

        # It's not a NACK. Check if it's a known command or an ACK.
        cmd = frame[CMD_IDX]
        if cmd in command_handler.COMMAND_MAP:
            return FrameType.COMMAND  # It's a zero-payload command
        else:
            return FrameType.ACK

    def evaluate_crc(self, frame: bytes) -> bool:
        """
        Validates the CRC of a well-formed frame and sends an ACK or NACK.
        """
        if crc_16.calculate_crc(frame) == crc_16.extract_checksum_received(frame):
            ack_frame = self.ack(frame)
            if uart.send_data(ack_frame):
                logging.info("Sent ACK to PIC")
            else:
                logging.error("Failed to send ACK")
            return True
        else:
            nack_frame = self.nack(UARTError.INVALID_CHECKSUM)
            if uart.send_data(nack_frame):
                logging.warning("Sent NACK to PIC (Invalid Checksum)")
            else:
                logging.error("Failed to send NACK")
            return False

    @staticmethod
    def ack(buffer: bytes) -> bytes:
        """
        Constructs an ACK frame in response to a received message.
        """
        ack_buffer = bytearray([0] * MINIMUM_BUFFER_SIZE)
        payload_length = buffer[DATA_LENGTH_IDX]

        # ack_buffer[DATA_LENGTH_IDX] is always zero in ACK & NACK frames.
        ack_buffer[HEADER_IDX] = HEADER
        ack_buffer[CMD_IDX] = buffer[CMD_IDX]
        ack_buffer[DATA_LENGTH_IDX] = 0x00
        ack_buffer[CRC_MSB_IDX_OFFSET] = buffer[payload_length + CRC_MSB_IDX_OFFSET]
        ack_buffer[CRC_LSB_IDX_OFFSET] = buffer[payload_length + CRC_LSB_IDX_OFFSET]
        ack_buffer[MINIMUM_BUFFER_SIZE - 1] = STOP_BYTE

        return bytes(ack_buffer)

    @staticmethod
    def nack(error: UARTError) -> bytes:
        """
        Constructs a NACK frame to notify of a reception error.
        """
        if error.value >= UARTError.MAX_ERRORS.value:
            return b""

        # In NACK and ACK buffer, the content of "payload length" is always zero.
        nack_buffer = bytearray([HEADER, 0x00, 0x00, 0x00, 0x00, STOP_BYTE])

        if error == UARTError.BAD_FRAME:
            pass
        elif error == UARTError.INVALID_CHECKSUM:
            nack_buffer[CMD_IDX] = NACK_INVALID_FIELD_VALUE
            nack_buffer[CRC_MSB_IDX_OFFSET] = NACK_INVALID_FIELD_VALUE
            nack_buffer[CRC_LSB_IDX_OFFSET] = NACK_INVALID_FIELD_VALUE
        else:
            return b""

        return bytes(nack_buffer)


if __name__ == "__main__":
    """
    Standalone UART protocol test script.

    This script initializes the UART listener and continuously polls for
    valid data frames from the hardware, processing them as they arrive.
    """
    logging.info("--- Starting Standalone UART Protocol Test ---")

    protocol = UARTProtocol()

    try:
        # Initialize and start the low-level UART listener
        uart.start_listener(config.UART_PORT, config.BAUD_RATE)
        logging.info("UART Listener started.")

        while True:
            # Step 1: Pull all available data into the buffer
            protocol.pull_frame()

            # Step 2: Try to validate and extract a frame from the buffer
            frame = protocol.validate_and_extract_frame()

            if frame:
                # Step 3: Classify the frame to determine the next action
                frame_type = protocol.classify_frame(frame)
                logging.info(
                    f"Complete frame received: {frame.hex()} -> Type: {frame_type.name}"
                )

                # Step 4: Evaluate frame based on its type
                if frame_type == FrameType.COMMAND:
                    # Only COMMAND frames get a CRC check
                    if protocol.evaluate_crc(frame):
                        # If CRC is valid, execute the command
                        cmd_byte = frame[CMD_IDX]
                        logging.info(f"Executing received command: {cmd_byte}")
                        # We pass flash=None as this test script doesn't init it
                        command_handler.execute_command(cmd_byte, flash=None)

                elif frame_type == FrameType.ACK:
                    # Here you would handle the logic for a successful command
                    logging.info("ACK received. Previous command successful.")
                else:
                    # Here you would handle NACKs, e.g., by re-transmitting
                    logging.warning(
                        f"{frame_type.name} received. Previous command failed."
                    )

                # Clear queue after processing a frame
                logging.info(f"Cleared {uart.clear_queue()} items from queue.")

            # Small delay to prevent busy-waiting and high CPU usage (70ms)
            time.sleep(0.07)

    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received. Shutting down.")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}", exc_info=True)
    finally:
        # Ensure the UART listener is stopped on exit
        logging.info("Stopping UART listener...")
        uart.stop_listener()
        logging.info("--- UART Protocol Test Finished ---")
