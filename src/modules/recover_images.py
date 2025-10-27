import logging
from pathlib import Path
from typing import Optional
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules import flash_interface
from modules import config

# Configure module logger
logger = logging.getLogger(__name__)

# --- Constants ---
RECOVERY_DIR = "flash_recovered"
# Max spidev buffer (4096) minus 5 bytes for read command (1) and address (4)
READ_CHUNK_SIZE = 4091
INDEX_ENTRY_SIZE = 8
ADDRESS_SIZE = 4
ERASED_BYTE = 0xFF
DEFAULT_IMAGE_EXTENSION = ".jpg"


class ImageRecoveryError(Exception):
    """Custom exception for image recovery operations."""

    pass


def is_index_entry_empty(entry_bytes: list[int]) -> bool:
    """
    Check if an index entry is empty (all bytes are 0xFF).

    Args:
        entry_bytes: First 4 bytes of the index entry

    Returns:
        True if entry is empty, False otherwise
    """
    return entry_bytes[:ADDRESS_SIZE] == [ERASED_BYTE] * ADDRESS_SIZE


def parse_index_entry(entry_bytes: list[int]) -> tuple[int, int]:
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


def ensure_recovery_directory(directory: str) -> Path:
    """
    Ensure the recovery directory exists, creating it if necessary.

    Args:
        directory: Path to the recovery directory

    Returns:
        Path object for the recovery directory

    Raises:
        ImageRecoveryError: If directory cannot be created
    """
    recovery_path = Path(directory)

    try:
        if recovery_path.exists():
            logger.info(f"Using existing recovery directory: '{recovery_path}'")
        else:
            logger.info(f"Creating recovery directory: '{recovery_path}'")
            recovery_path.mkdir(parents=True, exist_ok=True)

        return recovery_path

    except Exception as e:
        raise ImageRecoveryError(f"Failed to create recovery directory: {e}")


def read_image_data_in_chunks(
    flash_chip: flash_interface.FlashMemory, start_addr: int, total_size: int
) -> Optional[bytearray]:
    """
    Read image data from flash memory in chunks.

    Args:
        flash_chip: FlashMemory instance
        start_addr: Starting address of the image data
        total_size: Total size of the image in bytes

    Returns:
        Bytearray containing the image data, or None if error
    """
    image_data = bytearray()
    bytes_read = 0

    logger.info(f"Reading {total_size:,} bytes from flash in chunks...")

    try:
        while bytes_read < total_size:
            # Calculate chunk size for this iteration
            bytes_to_read = min(READ_CHUNK_SIZE, total_size - bytes_read)
            chunk_address = start_addr + bytes_read

            # Read chunk from flash
            chunk_data = flash_chip.read_bytes(chunk_address, bytes_to_read)

            if not chunk_data:
                logger.error(f"Failed to read chunk at address 0x{chunk_address:08X}")
                return None

            image_data.extend(chunk_data)
            bytes_read += len(chunk_data)

            # Log progress for large files
            if total_size > 100_000:
                progress = (bytes_read / total_size) * 100
                logger.debug(
                    f"Progress: {progress:.1f}% ({bytes_read}/{total_size} bytes)"
                )

        return image_data

    except Exception as e:
        logger.error(f"Error reading image data: {e}")
        return None


def save_recovered_image(
    image_data: bytearray,
    image_number: int,
    recovery_dir: Path,
    extension: str = DEFAULT_IMAGE_EXTENSION,
) -> bool:
    """
    Save recovered image data to a file.

    Args:
        image_data: Image data to save
        image_number: Sequential number for the image
        recovery_dir: Directory to save the image
        extension: File extension (default: .jpg)

    Returns:
        True if save successful, False otherwise
    """
    file_name = f"image_{image_number}{extension}"
    file_path = recovery_dir / file_name

    try:
        with open(file_path, "wb") as f:
            f.write(image_data)

        logger.info(f"SUCCESS: Saved to '{file_path}' ({len(image_data):,} bytes)")
        return True

    except IOError as e:
        logger.error(f"Failed to write file to '{file_path}': {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error saving file: {e}")
        return False


def recover_single_image(
    flash_chip: flash_interface.FlashMemory,
    image_number: int,
    start_addr: int,
    end_addr: int,
    recovery_dir: Path,
) -> bool:
    """
    Recover a single image from flash memory.

    Args:
        flash_chip: FlashMemory instance
        image_number: Sequential number for this image
        start_addr: Starting address of the image data
        end_addr: Ending address of the image data
        recovery_dir: Directory to save recovered images

    Returns:
        True if recovery successful, False otherwise
    """
    total_size = end_addr - start_addr

    logger.info(f"\n{'='*50}")
    logger.info(f"Recovering Image {image_number}")
    logger.info("=" * 50)
    logger.info(f"Data location:  0x{start_addr:08X} to 0x{end_addr:08X}")
    logger.info(f"Total size:     {total_size:,} bytes")

    # Validate size
    if total_size <= 0:
        logger.error(f"Invalid image size: {total_size} bytes")
        return False

    # Read image data in chunks
    image_data = read_image_data_in_chunks(flash_chip, start_addr, total_size)

    if image_data is None:
        logger.error("Failed to read image data from flash")
        return False

    # Verify size matches expected
    if len(image_data) != total_size:
        logger.error(
            f"Size mismatch: Expected {total_size:,} bytes, "
            f"got {len(image_data):,} bytes"
        )
        return False

    # Save to file
    return save_recovered_image(image_data, image_number, recovery_dir)


def scan_and_recover_images(
    flash_chip: flash_interface.FlashMemory, recovery_dir: Path
) -> int:
    """
    Scan the flash memory index and recover all found images.

    Args:
        flash_chip: FlashMemory instance
        recovery_dir: Directory to save recovered images

    Returns:
        Number of images successfully recovered
    """
    logger.info("\n" + "=" * 50)
    logger.info("Starting Image Recovery Process")
    logger.info("=" * 50)

    current_index_addr = config.INDEX_1ST
    image_count = 0
    recovered_count = 0

    # Scan the index section
    while current_index_addr <= config.INDEX_END:
        entry_bytes = flash_chip.read_bytes(current_index_addr, INDEX_ENTRY_SIZE)

        # Check for empty slot (end of valid entries)
        if is_index_entry_empty(entry_bytes):
            logger.info(
                f"Found empty index slot at 0x{current_index_addr:08X}. "
                "End of stored images."
            )
            break

        # Parse the index entry
        start_addr, end_addr = parse_index_entry(entry_bytes)
        image_count += 1

        logger.debug(f"Index entry at 0x{current_index_addr:08X}")

        # Attempt to recover the image
        if recover_single_image(
            flash_chip, image_count, start_addr, end_addr, recovery_dir
        ):
            recovered_count += 1

        # Move to next index entry
        current_index_addr += INDEX_ENTRY_SIZE

    return recovered_count, image_count


def run_recovery(flash_chip: flash_interface.FlashMemory, recovery_dir: Path) -> None:
    """
    Run the complete image recovery process.

    Args:
        flash_chip: FlashMemory instance
        recovery_dir: Directory to save recovered images
    """
    recovered_count, total_count = scan_and_recover_images(flash_chip, recovery_dir)

    # Print summary
    logger.info("\n" + "=" * 50)
    logger.info("Recovery Complete")
    logger.info("=" * 50)

    if total_count == 0:
        logger.info("No valid image entries found in the index")
    else:
        logger.info(f"Total images found: {total_count}")
        logger.info(f"Successfully recovered: {recovered_count}")
        logger.info(f"Failed: {total_count - recovered_count}")
        logger.info(f"Recovery directory: {recovery_dir.absolute()}")


def main() -> None:
    """Main entry point for the image recovery script."""
    try:
        # Ensure recovery directory exists
        recovery_dir = ensure_recovery_directory(RECOVERY_DIR)

        # Use context manager for automatic cleanup
        with flash_interface.FlashMemory(
            bus=config.SPI_BUS, device=config.SPI_DEVICE
        ) as flash_chip:
            run_recovery(flash_chip, recovery_dir)

    except flash_interface.FlashMemoryError as e:
        logger.error(f"Flash memory error: {e}")
    except ImageRecoveryError as e:
        logger.error(f"Recovery error: {e}")
    except KeyboardInterrupt:
        logger.info("\nRecovery process stopped by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    main()
