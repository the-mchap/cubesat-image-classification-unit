import spidev
import time
import logging
from typing import Optional, List

from modules import config

"""Interface with flash memory."""

# Configure module logger
logger = logging.getLogger(__name__)


class FlashMemoryError(Exception):
    """Custom exception for flash memory operations."""

    pass


class FlashMemory:
    # Command Set
    CMD_WRITE_ENABLE = 0x06
    CMD_READ_STATUS_REG1 = 0x05
    CMD_PAGE_PROGRAM_4B = 0x12
    CMD_READ_DATA_4B = 0x13
    CMD_SECTOR_ERASE_4KB_4B = 0x21
    CMD_BLOCK_ERASE_32KB_4B = 0x5C
    CMD_BLOCK_ERASE_64KB_4B = 0xDC
    CMD_DIE_ERASE_4B = 0xC4

    # Status Register Bits
    STATUS_WIP_BIT = 0b00000001

    # Memory Layout
    PAGE_SIZE = 256  # bytes
    SECTOR_SIZE_4KB = 4 * 1024
    SECTOR_SIZE_32KB = 32 * 1024
    SECTOR_SIZE_64KB = 64 * 1024
    DIE_SIZE = 0x04000000  # 64MB per die for 1Gbit chip

    # Erase size mapping
    ERASE_SIZES = {
        4: (CMD_SECTOR_ERASE_4KB_4B, SECTOR_SIZE_4KB),
        32: (CMD_BLOCK_ERASE_32KB_4B, SECTOR_SIZE_32KB),
        64: (CMD_BLOCK_ERASE_64KB_4B, SECTOR_SIZE_64KB),
    }

    # Timing constants
    WIP_POLL_INTERVAL = 0.001  # seconds
    DIE_ERASE_TIMEOUT = 60  # seconds

    def __init__(
        self,
        bus: int = config.SPI_BUS,
        device: int = config.SPI_DEVICE,
        max_speed_hz: int = 10_000_000,
        mode: int = 0,
    ):
        """
        Initialize the SPI connection to flash memory.

        Args:
            bus: SPI bus number
            device: SPI device number
            max_speed_hz: Maximum SPI speed in Hz (default: 10MHz)
            mode: SPI mode (default: 0)

        Raises:
            FlashMemoryError: If SPI initialization fails
        """
        self.spi: Optional[spidev.SpiDev] = None
        self.is_open = False
        self.bus = bus
        self.device = device

        try:
            self.spi = spidev.SpiDev()
            self.spi.open(bus, device)
            self.is_open = True
            self.spi.max_speed_hz = max_speed_hz
            self.spi.mode = mode

            logger.info(
                f"SPI connection opened on bus {bus}, device {device} "
                f"(Mode: {self.spi.mode}, Speed: {self.spi.max_speed_hz / 1e6:.1f} MHz)"
            )
        except FileNotFoundError:
            error_msg = (
                f"SPI bus {bus} or device {device} not found. "
                "Please ensure SPI is enabled with 'sudo dietpi-config'."
            )
            logger.error(error_msg)
            raise FlashMemoryError(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error during SPI setup: {e}"
            logger.error(error_msg)
            raise FlashMemoryError(error_msg)

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures cleanup."""
        self.close()

    def close(self) -> None:
        """Close the SPI connection."""
        if self.spi and self.is_open:
            self.spi.close()
            self.is_open = False
            logger.info("SPI connection closed")

    def _check_connection(self) -> None:
        """Verify SPI connection is open."""
        if not self.is_open:
            raise FlashMemoryError("SPI connection is not open")

    def _address_to_bytes(self, address: int) -> List[int]:
        """
        Convert a 32-bit address to a list of 4 bytes (big-endian).

        Args:
            address: Memory address

        Returns:
            List of 4 address bytes
        """
        return list(address.to_bytes(4, "big"))

    def _wait_for_write_complete(self, timeout: float = 10.0) -> bool:
        """
        Poll the status register until the WIP bit is cleared.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if write completed, False if timeout

        Raises:
            FlashMemoryError: If operation times out
        """
        start_time = time.time()
        while True:
            status = self.spi.xfer2([self.CMD_READ_STATUS_REG1, 0x00])[1]
            if (status & self.STATUS_WIP_BIT) == 0:
                return True

            if time.time() - start_time > timeout:
                raise FlashMemoryError(
                    f"Write operation timeout after {timeout} seconds"
                )

            time.sleep(self.WIP_POLL_INTERVAL)

    def _write_enable(self) -> None:
        """Send the Write Enable (WREN) command."""
        self.spi.xfer2([self.CMD_WRITE_ENABLE])

    def read_bytes(self, address: int, length: int) -> List[int]:
        """
        Read a specified number of bytes from flash memory.

        Args:
            address: Starting address to read from
            length: Number of bytes to read

        Returns:
            List of bytes read from memory

        Raises:
            FlashMemoryError: If connection is not open
        """
        self._check_connection()

        if length <= 0:
            logger.warning("Read length must be positive")
            return []

        addr_bytes = self._address_to_bytes(address)
        dummy_bytes = [0x00] * length
        command = [self.CMD_READ_DATA_4B] + addr_bytes + dummy_bytes

        # Skip command byte (1) + address bytes (4) = 5 bytes
        response = self.spi.xfer2(command)[5:]

        logger.debug(f"Read {len(response)} bytes from address 0x{address:08X}")
        return response

    def write_bytes(self, address: int, data: List[int]) -> bool:
        """
        Write data to flash memory, handling page boundaries correctly.

        Args:
            address: Starting address to write to
            data: List of bytes to write

        Returns:
            True if write successful, False otherwise

        Raises:
            FlashMemoryError: If connection is not open
        """
        self._check_connection()

        if not data:
            logger.warning("No data to write")
            return False

        data_len = len(data)
        bytes_written = 0

        logger.debug(f"Writing {data_len} bytes to address 0x{address:08X}")

        try:
            while bytes_written < data_len:
                current_address = address + bytes_written

                # Calculate bytes until next page boundary
                offset_in_page = current_address % self.PAGE_SIZE
                bytes_to_page_end = self.PAGE_SIZE - offset_in_page
                bytes_left_to_write = data_len - bytes_written

                # Write up to page boundary or remaining data
                chunk_size = min(bytes_to_page_end, bytes_left_to_write)
                data_chunk = data[bytes_written : bytes_written + chunk_size]

                self._write_page(current_address, data_chunk)
                bytes_written += chunk_size

            logger.info(f"Successfully wrote {data_len} bytes to 0x{address:08X}")
            return True

        except Exception as e:
            logger.error(f"Write failed at byte {bytes_written}: {e}")
            return False

    def _write_page(self, address: int, data_chunk: List[int]) -> None:
        """
        Write a single page-aligned chunk to flash.

        Args:
            address: Page-aligned starting address
            data_chunk: Data to write (up to PAGE_SIZE bytes)

        Raises:
            FlashMemoryError: If connection is not open or chunk is too large
        """
        self._check_connection()

        if not data_chunk:
            return

        if len(data_chunk) > self.PAGE_SIZE:
            raise FlashMemoryError(
                f"Chunk size {len(data_chunk)} exceeds page size {self.PAGE_SIZE}"
            )

        self._write_enable()
        addr_bytes = self._address_to_bytes(address)
        command = [self.CMD_PAGE_PROGRAM_4B] + addr_bytes + data_chunk
        self.spi.xfer2(command)
        self._wait_for_write_complete()

    def erase_sector(self, address: int, size_kb: int = 4) -> bool:
        """
        Erase a sector of flash memory.

        Args:
            address: Address within the sector to erase
            size_kb: Sector size in KB (4, 32, or 64)

        Returns:
            True if erase successful, False otherwise

        Raises:
            FlashMemoryError: If connection is not open or invalid size
        """
        self._check_connection()

        if size_kb not in self.ERASE_SIZES:
            raise FlashMemoryError(
                f"Invalid erase size {size_kb}KB. Must be 4, 32, or 64."
            )

        erase_cmd, sector_size = self.ERASE_SIZES[size_kb]

        # Align address to sector boundary for logging
        aligned_address = (address // sector_size) * sector_size

        logger.info(
            f"Erasing {size_kb}KB sector at 0x{aligned_address:08X} "
            f"(requested address: 0x{address:08X})"
        )

        try:
            self._write_enable()
            addr_bytes = self._address_to_bytes(address)
            command = [erase_cmd] + addr_bytes
            self.spi.xfer2(command)
            self._wait_for_write_complete(timeout=30.0)

            logger.info(f"Successfully erased {size_kb}KB sector")
            return True

        except Exception as e:
            logger.error(f"Sector erase failed: {e}")
            return False

    def erase_die(self, die_number: int) -> bool:
        """
        Erase an entire die (very slow operation).

        For a 1Gbit chip:
        - Die 0: 0x00000000 - 0x03FFFFFF (64MB)
        - Die 1: 0x04000000 - 0x07FFFFFF (64MB)

        Args:
            die_number: Die to erase (0 or 1)

        Returns:
            True if erase successful, False otherwise

        Raises:
            FlashMemoryError: If connection is not open or invalid die number
        """
        self._check_connection()

        if die_number not in (0, 1):
            raise FlashMemoryError(f"Invalid die number {die_number}. Must be 0 or 1.")

        address = die_number * self.DIE_SIZE

        logger.warning(
            f"Starting Die {die_number} erase at 0x{address:08X}. "
            f"This may take up to {self.DIE_ERASE_TIMEOUT} seconds..."
        )

        try:
            self._write_enable()
            addr_bytes = self._address_to_bytes(address)
            command = [self.CMD_DIE_ERASE_4B] + addr_bytes
            self.spi.xfer2(command)
            self._wait_for_write_complete(timeout=self.DIE_ERASE_TIMEOUT)

            logger.info(f"Die {die_number} erase complete")
            return True

        except Exception as e:
            logger.error(f"Die erase failed: {e}")
            return False
