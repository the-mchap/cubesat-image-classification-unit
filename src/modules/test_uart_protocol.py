"""
This module contains unit tests for the UARTProtocol class.

Purpose:
- To verify the correctness of the frame parsing and handling logic in isolation,
  without requiring physical hardware.
- To prevent regressions by ensuring that modifications to the protocol logic
  do not break existing functionality.
"""

import unittest
from unittest.mock import patch, MagicMock

# Assuming the script is run from the project root or the modules directory is in PYTHONPATH
from .uart_protocol import UARTProtocol, FrameType
from .command_handler import COMMAND_MAP
from .crc_16 import calculate_crc


class TestUARTProtocol(unittest.TestCase):
    """
    Test suite for the UARTProtocol class.
    """

    def setUp(self):
        """Set up a new UARTProtocol instance for each test."""
        self.protocol = UARTProtocol()

    @patch('modules.uart.get_data')
    def test_frame_parsing_with_single_valid_frame(self, mock_get_data: MagicMock):
        """
        Purpose: To verify that the combination of `pull_frame` and
        `validate_and_extract_frame` can correctly parse a single, complete,
        and valid frame from the UART queue.
        """
        # 1. Setup: Construct a valid test frame
        header = 0x3E
        cmd = 0x01
        payload = b'\xAB\xCD'
        payload_len = len(payload)
        stop_byte = 0x0A
        crc_data = bytes([cmd, payload_len]) + payload
        # The CRC in the real implementation is calculated on a slightly different slice
        # but for a mock test, this is sufficient to create a valid frame structure.
        crc_value = calculate_crc(bytes([header, cmd, payload_len]) + payload)
        crc_msb = (crc_value >> 8) & 0xFF
        crc_lsb = crc_value & 0xFF
        full_frame = bytes([header, cmd, payload_len]) + payload + bytes([crc_msb, crc_lsb, stop_byte])

        # 2. Mocking: Configure the mock for uart.get_data
        mock_get_data.side_effect = [bytes([b]) for b in full_frame] + [None]

        # 3. Execution
        self.protocol.pull_frame()
        result_frame = self.protocol.validate_and_extract_frame()

        # 4. Assertion
        self.assertEqual(result_frame, full_frame)
        self.assertEqual(len(self.protocol.buffer), 0)

    def test_classify_frame_command_with_payload(self):
        """
        Purpose: To verify that a frame with a payload (length > 6) is
        correctly classified as a COMMAND.
        """
        # Frame with 1-byte payload, total length 7
        frame = b'\x3E\x01\x01\xAA\x00\x00\x0A'
        frame_type = self.protocol.classify_frame(frame)
        self.assertEqual(frame_type, FrameType.COMMAND)

    def test_classify_frame_nack_checksum(self):
        """
        Purpose: To verify that the specific NACK for checksum error pattern
        is correctly classified.
        """
        frame = bytes([0x3E, 0xFF, 0x00, 0xFF, 0xFF, 0x0A])
        frame_type = self.protocol.classify_frame(frame)
        self.assertEqual(frame_type, FrameType.NACK_CHECKSUM)

    def test_classify_frame_nack_format(self):
        """
        Purpose: To verify that the specific NACK for format error pattern
        is correctly classified.
        """
        frame = bytes([0x3E, 0x00, 0x00, 0x00, 0x00, 0x0A])
        frame_type = self.protocol.classify_frame(frame)
        self.assertEqual(frame_type, FrameType.NACK_FORMAT)

    def test_classify_frame_ack(self):
        """
        Purpose: To verify that a 6-byte frame whose command byte is NOT
        in the COMMAND_MAP is classified as an ACK.
        """
        # Assume 0x99 is NOT a command the Pi can execute
        self.assertNotIn(0x99, COMMAND_MAP)
        frame = bytes([0x3E, 0x99, 0x00, 0x12, 0x34, 0x0A])
        frame_type = self.protocol.classify_frame(frame)
        self.assertEqual(frame_type, FrameType.ACK)

    def test_classify_frame_zero_payload_command(self):
        """
        Purpose: To verify that a 6-byte frame whose command byte IS
        in the COMMAND_MAP is classified as a COMMAND.
        """
        # The STATUS command (2) is a known zero-payload command
        status_command_byte = 2
        self.assertIn(status_command_byte, COMMAND_MAP)
        frame = bytes([0x3E, status_command_byte, 0x00, 0x56, 0x78, 0x0A])
        frame_type = self.protocol.classify_frame(frame)
        self.assertEqual(frame_type, FrameType.COMMAND)

# This allows the test to be run from the command line
if __name__ == '__main__':
    unittest.main()
