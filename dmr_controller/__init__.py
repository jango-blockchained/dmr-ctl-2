"""
Digital Media Controller for DLNA/UPnP networks.
Enables media streaming, device discovery, and control functionality.
"""

__version__ = '0.1.0'

from .receiver_controller import BaseReceiverController
from .yamaha_controller import YamahaController

__all__ = ['BaseReceiverController', 'YamahaController']
