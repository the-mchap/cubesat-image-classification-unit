import time
import logging
from typing import Optional

from modules import flash_actions
from modules import uart
from modules import flash_interface
from modules import system_actions
from modules import init_setup
from modules import command_handler
from modules import uart_protocol

# Configure module logger
logger = logging.getLogger(__name__)

# --- Constants ---
MAIN_LOOP_INTERVAL = 0.1  # seconds


def run_main_loop(
    protocol: uart_protocol.UARTProtocol,
    flash: Optional[flash_interface.FlashMemory],
    next_index_addr: Optional[int],
    next_data_addr: Optional[int],
) -> None:
    """
    Run the main application loop.

    Args:
        protocol: The UART protocol instance for handling frames.
        flash: Optional FlashMemory instance for flash operations
        next_index_addr: Next available index address in flash
        next_data_addr: Next available data address in flash

    Raises:
        ShutdownRequested: If graceful shutdown is requested via command
    """
    logger.info("Entering main loop (Press Ctrl+C to exit)")

    loop_count = 0

    try:
        while True:

            #### Perform the main periodic tasks here ####
            #
            # HERE CAN GO A FUNCTION TO TAKE PHOTO
            # cam.take_photo()

            # HERE CAN GO A FUNCTION TO RUN THE CNN
            # deep.run_cnn()

            # HERE CAN GO A FUNCTION TO ADD METADATA
            # metada.add_comment()

            # Idk, just a wild idea.
            ############################################

            ########## UART frame checking ##########
            # It is not polling. The bytes received
            # are queued and only checked and vali-
            # -dated here if there's any to do so
            ####
            # Pull all available data into the buffer
            protocol.pull_frame()

            # Try to validate and extract a frame from the buffer
            frame = protocol.validate_and_extract_frame()

            if frame:
                # Classify the frame to determine the next action
                frame_type = protocol.classify_frame(frame)
                logging.info(
                    f"Complete frame received: {frame.hex()} -> Type: {frame_type.name}"
                )

                # Evaluate frame based on its type
                if frame_type == uart_protocol.FrameType.COMMAND:
                    # Only COMMAND frames get a CRC check
                    if protocol.evaluate_crc(frame):
                        # If CRC is valid, execute the command
                        cmd_byte = frame[uart_protocol.CMD_IDX]
                        logging.info(f"Executing received command: {cmd_byte}")
                        command_handler.execute_command(cmd_byte, flash)

                elif frame_type == uart_protocol.FrameType.ACK:
                    # Here it should be handled the logic for a successful command (Not much needed tbh)
                    logging.info("ACK received. Previous command successful.")
                else:
                    # Here it should be handled NACKs, by re-transmitting.
                    logging.warning(
                        f"{frame_type.name} received. Previous command failed."
                    )
            ############################################

            # THIS ONE IS FOR LASC. Store on flash every 10 iterations.
            if (loop_count % 10 == 0) and (loop_count != 0):
                if flash and next_index_addr is not None and next_data_addr is not None:
                    logger.info(f"Loop {loop_count}: Storing image to flash...")
                    result = flash_actions.store_image_to_flash(
                        flash, next_index_addr, next_data_addr
                    )
                    if result:
                        next_index_addr, next_data_addr = result
                    else:
                        logger.error(
                            "Failed to store image. Will retry on the next interval."
                        )

            loop_count += 1

            # if loop_count % 100 == 0:
            #     logger.debug(
            #         f"Main loop heartbeat (iteration {loop_count}, "
            #         f"queue size: {uart.get_queue_size()})"
            #     )

            time.sleep(MAIN_LOOP_INTERVAL)

    except KeyboardInterrupt:
        logger.info("\nShutdown signal received (Ctrl+C)")
        raise


def main() -> None:
    """Main entry point for the application."""
    logger.info("=" * 50)
    logger.info("Starting Application")
    logger.info("=" * 50)

    # Log available commands
    command_handler.log_available_commands()
    logger.info("=" * 50)

    flash = None
    shutdown_type = None  # Track what type of shutdown was requested
    next_index_addr, next_data_addr = None, None

    try:
        # Initialize UART and UART Protocol
        init_setup.initialize_uart()
        protocol = uart_protocol.UARTProtocol()

        # Initialize flash memory (optional)
        flash = init_setup.initialize_flash()
        if not flash:
            logger.warning("Running without flash memory support")
        else:
            # Find next available flash addresses
            addrs = flash_actions.find_next_available_address(flash)
            if addrs:
                next_index_addr, next_data_addr = addrs
            else:
                logger.error("Flash memory is full, cannot store images.")

        # Run main application loop
        run_main_loop(protocol, flash, next_index_addr, next_data_addr)

    except uart.ShutdownRequested as e:
        logger.info(f"Graceful shutdown requested: {e}")
        # Determine shutdown type from the exception message
        if "poweroff" in str(e).lower():
            shutdown_type = "poweroff"
        elif "reboot" in str(e).lower():
            shutdown_type = "reboot"
    except init_setup.ApplicationError as e:
        logger.error(f"Application error: {e}")
    except KeyboardInterrupt:
        logger.info("Shutdown via keyboard interrupt")
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
    finally:
        system_actions.cleanup(flash)
        logger.info("=" * 50)
        logger.info("Application Shutdown Complete")
        logger.info("=" * 50)

        # Perform system shutdown if requested
        if shutdown_type == "poweroff":
            system_actions.perform_system_poweroff()
        elif shutdown_type == "reboot":
            system_actions.perform_system_reboot()


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    main()
