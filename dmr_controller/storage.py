import json
import logging
import datetime
from pathlib import Path
from typing import List, Dict, TypedDict, Tuple, Optional, Union, Any

import appdirs

logger = logging.getLogger(__name__)

class DeviceDict(TypedDict):
    friendly_name: str
    location: str
    device_type: str

class StoredData(TypedDict):
    """Type definition for stored device data including servers and renderers."""
    servers: List[DeviceDict]
    renderers: List[DeviceDict]
    timestamp: str

class DeviceStorage:
    def __init__(self):
        self.app_dir = Path(appdirs.user_data_dir("dmr_controller"))
        self.devices_file = self.app_dir / "devices.json"
        self._ensure_directory()

    def _ensure_directory(self):
        """Create storage directory if it doesn't exist."""
        self.app_dir.mkdir(parents=True, exist_ok=True)

    def _validate_device_dict(self, device: Union[Dict[str, Any], DeviceDict]) -> bool:
        """Validate that a device dictionary has all required fields.
        
        Args:
            device: Dictionary containing device information
            
        Returns:
            bool: True if the dictionary has all required fields with string values
        """
        required_fields = {'friendly_name', 'location', 'device_type'}
        return all(
            isinstance(device.get(field), str)
            for field in required_fields
        )

    def save_devices(self, servers: List[DeviceDict], renderers: List[DeviceDict]) -> bool:
        """Save discovered devices to storage.
        
        Args:
            servers: List of media server dictionaries
            renderers: List of media renderer dictionaries
            
        Returns:
            bool: True if save was successful, False otherwise
        """
        try:
            # Validate device dictionaries
            if not all(self._validate_device_dict(s) for s in servers):
                logger.error("Invalid server data format")
                return False
            if not all(self._validate_device_dict(r) for r in renderers):
                logger.error("Invalid renderer data format")
                return False

            data: StoredData = {
                "servers": servers,
                "renderers": renderers,
                "timestamp": datetime.datetime.now().isoformat()
            }
            
            with self.devices_file.open('w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error saving devices: {e}")
            return False

    def load_devices(self) -> Tuple[List[DeviceDict], List[DeviceDict]]:
        """Load devices from storage.
        
        Returns:
            Tuple containing lists of server and renderer dictionaries
        """
        try:
            if not self.devices_file.exists():
                return [], []
            
            with self.devices_file.open('r') as f:
                data: StoredData = json.load(f)
            
            # Validate loaded data
            servers = data.get("servers", [])
            renderers = data.get("renderers", [])
            
            if not all(self._validate_device_dict(s) for s in servers):
                logger.error("Invalid server data in storage")
                return [], []
            if not all(self._validate_device_dict(r) for r in renderers):
                logger.error("Invalid renderer data in storage")
                return [], []
                
            return servers, renderers
        except Exception as e:
            logger.error(f"Error loading devices: {e}")
            return [], [] 