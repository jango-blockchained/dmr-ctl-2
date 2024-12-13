from abc import ABC, abstractmethod
from typing import Optional, Dict, List
import logging

logger = logging.getLogger(__name__)

class BaseReceiverController(ABC):
    """Abstract base class for receiver controllers."""
    
    @abstractmethod
    def get_status(self) -> Dict:
        """Get current receiver status.
        
        Returns:
            Dict containing at least:
            - power (bool): Power state
            - volume (int): Volume level (0-100)
            - mute (bool): Mute state
            - input (str): Current input source
        """
        pass
    
    @abstractmethod
    def set_power(self, power: bool) -> bool:
        """Set power state.
        
        Args:
            power (bool): True for on, False for off/standby
            
        Returns:
            bool: True if successful
        """
        pass
    
    @abstractmethod
    def set_volume(self, volume: int) -> bool:
        """Set volume level.
        
        Args:
            volume (int): Volume level (0-100)
            
        Returns:
            bool: True if successful
        """
        pass
    
    @abstractmethod
    def set_input(self, input_source: str) -> bool:
        """Set input source.
        
        Args:
            input_source (str): Input source name
            
        Returns:
            bool: True if successful
        """
        pass
    
    @abstractmethod
    def set_mute(self, mute: bool) -> bool:
        """Set mute state.
        
        Args:
            mute (bool): True to mute, False to unmute
            
        Returns:
            bool: True if successful
        """
        pass
    
    @abstractmethod
    def get_input_list(self) -> List[str]:
        """Get available input sources.
        
        Returns:
            List[str]: List of available input source names
        """
        pass 