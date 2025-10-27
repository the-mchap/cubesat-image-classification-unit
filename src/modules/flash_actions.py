import logging
from typing import Optional, Tuple, List

from modules import flash_interface
from modules import config
from modules import photo_cnn_mockup

# Configure module logger
logger = logging.getLogger(__name__)

# --- Constants ---
INDEX_ENTRY_SIZE = 8  # bytes (4-byte start + 4-byte end address)
ADDRESS_SIZE = 4  # bytes
ERASED_BYTE = 0xFF


class FlashStorageError(Exception):
    """Custom exception for flash storage operations."""

    pass


def is_index_entry_empty(entry_bytes: List[int]) -> bool:
    """
    Check if an index entry is empty (all bytes are 0xFF).

    Args:
        entry_bytes: 8 bytes of the index entry

    Returns:
        True if entry is empty, False otherwise. Empty -> 0xFFFFFFFFFFFFFFFF.
    """
    return entry_bytes[:INDEX_ENTRY_SIZE] == [ERASED_BYTE] * INDEX_ENTRY_SIZE


def parse_index_entry(entry_bytes: List[int]) -> Tuple[int, int]:
    """
    Parse an 8-byte index entry into start and end addresses.

    Args:
        entry_bytes: 8 bytes representing the index entry

    Returns:
        Tuple of (start_address, end_address)
    """
    start_addr = int.from_bytes(entry_bytes[:ADDRESS_SIZE], "big")
    end_addr = int.from_bytes(entry_bytes[ADDRESS_SIZE:], "big")
    return start_addr, end_addr


def create_index_entry(start_addr: int, end_addr: int) -> List[int]:
    """
    Create an 8-byte index entry from start and end addresses.

    Args:
        start_addr: Starting address of the data
        end_addr: Ending address of the data

    Returns:
        List of 8 bytes representing the index entry
    """
    start_bytes = list(start_addr.to_bytes(ADDRESS_SIZE, "big"))
    end_bytes = list(end_addr.to_bytes(ADDRESS_SIZE, "big"))
    return start_bytes + end_bytes


def find_next_available_address(
    flash_chip: flash_interface.FlashMemory,
) -> Tuple[Optional[int], Optional[int]]:
    """
    Scan the Index Section to find the next free slot for an image.

    Args:
        flash_chip: FlashMemory instance

    Returns:
        Tuple of (next_index_address, next_data_address) or (None, None) if full
    """
    logger.info("Scanning index for next available address...")

    current_index_addr = config.INDEX_1ST
    last_data_end_addr = config.DATA_1ST

    while current_index_addr <= config.INDEX_END:
        # Read an 8-byte index entry
        entry_bytes = flash_chip.read_bytes(current_index_addr, INDEX_ENTRY_SIZE)

        # Check if this slot is empty
        if is_index_entry_empty(entry_bytes):
            logger.info(
                f"Found free index slot at 0x{current_index_addr:08X}, "
                f"next data address: 0x{last_data_end_addr:08X}"
            )
            return current_index_addr, last_data_end_addr

        # Parse the end address to find where the next data starts
        _, last_data_end_addr = parse_index_entry(entry_bytes)

        # Move to next index slot
        current_index_addr += INDEX_ENTRY_SIZE

    logger.error("Index section is full!")
    return None, None


def read_image_data(image_path: str) -> Optional[bytes]:
    """
    Read image data from file.

    Args:
        image_path: Path to the image file

    Returns:
        Image data as bytes, or None if error
    """
    try:
        with open(image_path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"Image file not found: {image_path}")
        return None
    except Exception as e:
        logger.error(f"Error reading image file: {e}")
        return None


def validate_storage_capacity(
    next_data_addr: int, image_size: int, next_index_addr: int
) -> bool:
    """
    Validate that there's enough space in both data and index sections.

    Args:
        next_data_addr: Next available data address
        image_size: Size of the image to store
        next_index_addr: Next available index address

    Returns:
        True if there's enough space, False otherwise
    """
    # Check data section capacity
    if next_data_addr + image_size > config.DATA_END:
        logger.error(
            f"Insufficient space in Data Section. "
            f"Required: {image_size} bytes, "
            f"Available: {config.DATA_END - next_data_addr} bytes"
        )
        return False

    # Check index section capacity
    if next_index_addr > config.INDEX_END:
        logger.error("Insufficient space in Index Section")
        return False

    return True


def _store_image_to_flash(
    flash_chip: flash_interface.FlashMemory,
    image_data: bytes,
    next_index_addr: int,
    next_data_addr: int,
) -> Tuple[int, int]:
    """
    Store image data to flash and update the index.

    Args:
        flash_chip: FlashMemory instance
        image_data: Image data to store
        next_index_addr: Address for the index entry
        next_data_addr: Address for the image data

    Returns:
        Tuple of (new_index_address, new_data_address) for next operation

    Raises:
        FlashStorageError: If write operation fails
    """
    image_size = len(image_data)

    # Write image data
    logger.info(f"Writing {image_size} bytes to data address 0x{next_data_addr:08X}...")
    if not flash_chip.write_bytes(next_data_addr, list(image_data)):
        raise FlashStorageError("Failed to write image data to flash")

    # Create and write index entry
    start_addr = next_data_addr
    end_addr = next_data_addr + image_size
    index_entry = create_index_entry(start_addr, end_addr)

    logger.info(
        f"Writing index entry at 0x{next_index_addr:08X}: "
        f"Start=0x{start_addr:08X}, End=0x{end_addr:08X}"
    )
    if not flash_chip.write_bytes(next_index_addr, index_entry):
        raise FlashStorageError("Failed to write index entry to flash")

    # Return updated addresses for next operation
    return next_index_addr + INDEX_ENTRY_SIZE, end_addr


def print_index_summary(flash_chip: flash_interface.FlashMemory) -> None:
    """
    Read and print a summary of all valid image entries in the flash index.

    Args:
        flash_chip: FlashMemory instance
    """
    logger.info("\n" + "=" * 50)
    logger.info("Flash Index Summary")
    logger.info("=" * 50)

    current_index_addr = config.INDEX_1ST
    image_count = 0

    while current_index_addr <= config.INDEX_END:
        entry_bytes = flash_chip.read_bytes(current_index_addr, INDEX_ENTRY_SIZE)

        # Check for empty slot (end of valid entries)
        if is_index_entry_empty(entry_bytes):
            break

        image_count += 1
        start_addr, end_addr = parse_index_entry(entry_bytes)
        image_size = end_addr - start_addr

        logger.info(f"\nImage {image_count}:")
        logger.info(f"  Index location:  0x{current_index_addr:08X}")
        logger.info(f"  Data start addr: 0x{start_addr:08X}")
        logger.info(f"  Data end addr:   0x{end_addr:08X}")
        logger.info(f"  Image size:      {image_size:,} bytes")

        current_index_addr += INDEX_ENTRY_SIZE

    if image_count == 0:
        logger.info("No valid image entries found in the index")
    else:
        logger.info(f"\nTotal images stored: {image_count}")

    logger.info("=" * 50)


def store_image_to_flash(
    flash_chip: flash_interface.FlashMemory,
    next_index_addr: int,
    next_data_addr: int,
) -> Optional[Tuple[int, int]]:
    """
    Performs a single cycle of simulating, capturing, and storing an image to flash.

    Args:
        flash_chip: FlashMemory instance.
        next_index_addr: The address for the next index entry.
        next_data_addr: The address for the next data block.

    Returns:
        A tuple of (new_index_address, new_data_address) for the next operation,
        or None if the operation failed.
    """
    logger.info("\n" + "=" * 50)
    logger.info("Starting image storage cycle")
    logger.info("=" * 50)

    # Simulate image capture
    classification, image_path = photo_cnn_mockup.simulate_image_capture(
        photo_cnn_mockup.MOCK_IMAGE_DIR
    )
    if not image_path:
        logger.error("Could not find an image to process. Halting.")
        return None

    # Read image data
    image_data = read_image_data(image_path)
    if not image_data:
        logger.error("Failed to read image data. Halting.")
        return None

    image_size = len(image_data)
    logger.info(f"Image size: {image_size:,} bytes")

    # Validate storage capacity
    if not validate_storage_capacity(next_data_addr, image_size, next_index_addr):
        logger.error("Insufficient storage capacity. Halting.")
        return None

    # Store image and update index
    try:
        new_next_index_addr, new_next_data_addr = _store_image_to_flash(
            flash_chip, image_data, next_index_addr, next_data_addr
        )
        logger.info("Cycle complete")
        return new_next_index_addr, new_next_data_addr

    except FlashStorageError as e:
        logger.error(f"Storage operation failed: {e}")
        return None
