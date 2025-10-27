"""--- Serial settings ---"""

UART_PORT = "/dev/ttyAMA0"
BAUD_RATE = 9600
SPI_BUS = 0
SPI_DEVICE = 1

""" --- Memory Sections ---"""
# Index Section boundaries
INDEX_1ST = 0x00000000
INDEX_END = 0x00002FFF
# Data Section boundaries
DATA_1ST = 0x00003000
DATA_END = 0x07FFFFFF

""" --- Project Settings ---"""
SLEEP_TIME = 0.1
# DEVICE_NAME = "ICU-RPI-01"
# IMAGE_DIR = "/home/dietpi/images/"
