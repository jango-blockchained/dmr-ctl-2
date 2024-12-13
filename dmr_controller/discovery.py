import upnpclient
import socket
import logging
from typing import List, Optional, Dict, Tuple
import requests
from xml.etree import ElementTree
import re

logger = logging.getLogger(__name__)

class DeviceDiscovery:
    """Handles DLNA/UPnP device discovery on the network."""
    
    def __init__(self):
        self.devices = []
        self.media_renderers = []
        self.media_servers = []
    
    def discover_devices(self) -> List[upnpclient.Device]:
        """
        Discover all DLNA/UPnP devices on the network.
        
        Returns:
            List of discovered UPnP devices
        """
        try:
            self.devices = upnpclient.discover()
            self._categorize_devices()
            return self.devices
        except socket.error as e:
            logger.error(f"Network error during device discovery: {e}")
            return []
        except Exception as e:
            logger.error(f"Error during device discovery: {e}")
            return []
    
    def _categorize_devices(self):
        """Categorize discovered devices into media renderers and servers."""
        self.media_renderers = []
        self.media_servers = []
        
        # Use a set to track unique server locations
        seen_server_locations = set()
        
        for device in self.devices:
            device_type = device.device_type.lower()
            if 'mediarenderer' in device_type:
                self.media_renderers.append(device)
            elif 'mediaserver' in device_type:
                # Only add the server if we haven't seen its location before
                if device.location not in seen_server_locations:
                    seen_server_locations.add(device.location)
                    self.media_servers.append(device)
    
    def get_media_renderers(self) -> List[upnpclient.Device]:
        """
        Get all discovered media renderer devices.
        
        Returns:
            List of media renderer devices
        """
        return self.media_renderers
    
    def get_media_servers(self) -> List[upnpclient.Device]:
        """
        Get all discovered media server devices.
        
        Returns:
            List of media server devices
        """
        return self.media_servers
    
    def get_device_by_name(self, name: str) -> Optional[upnpclient.Device]:
        """
        Find a device by its friendly name.
        
        Args:
            name: The friendly name of the device to find
            
        Returns:
            Device if found, None otherwise
        """
        for device in self.devices:
            if device.friendly_name.lower() == name.lower():
                return device
        return None
        
    def browse_media_server(self, server: upnpclient.Device, object_id: str = "0") -> List[Dict]:
        """
        Browse content on a media server.
        
        Args:
            server: The media server device to browse
            object_id: The ID of the object to browse (default is root "0")
            
        Returns:
            List of media items with their metadata
        """
        try:
            # Find the ContentDirectory service
            content_directory = next(
                (service for service in server.services 
                 if 'ContentDirectory' in service.service_type),
                None
            )
            
            if not content_directory:
                logger.error(f"ContentDirectory service not found for server: {server.friendly_name}")
                logger.debug(f"Available services: {[s.service_type for s in server.services]}")
                return []
            
            logger.info(f"Browsing media server: {server.friendly_name}, object_id: {object_id}")
            
            # Browse the content
            result = content_directory.Browse(
                ObjectID=object_id,
                BrowseFlag="BrowseDirectChildren",
                Filter="*",
                StartingIndex=0,
                RequestedCount=1000,
                SortCriteria=""
            )
            
            # Get parent container info if not at root
            parent_id = "0"
            if object_id != "0":
                try:
                    parent_result = content_directory.Browse(
                        ObjectID=object_id,
                        BrowseFlag="BrowseMetadata",
                        Filter="*",
                        StartingIndex=0,
                        RequestedCount=1,
                        SortCriteria=""
                    )
                    parent_didl = ElementTree.fromstring(parent_result["Result"])
                    container = parent_didl.find(".//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}container")
                    if container is not None:
                        parent_id = container.get('parentID', "0")
                except Exception as e:
                    logger.warning(f"Error getting parent info: {e}")
                    parent_id = "0"
            
            # Parse the DIDL-Lite response
            didl = ElementTree.fromstring(result["Result"])
            logger.debug(f"DIDL-Lite parsed, root tag: {didl.tag}")
            
            items = []
            
            # Add parent folder navigation if not at root
            if object_id != "0":
                items.append({
                    'id': parent_id,
                    'title': "📁 ..",
                    'type': 'container',
                    'is_parent': True
                })
            
            # Extract containers (folders)
            containers = didl.findall(".//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}container")
            logger.debug(f"Found {len(containers)} containers")
            for container in containers:
                title = container.find(".//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}title")
                if title is not None:
                    # Get child count if available
                    child_count = container.get('childCount', '')
                    child_info = f" ({child_count})" if child_count else ""
                    
                    items.append({
                        'id': container.get('id'),
                        'title': f"📁 {title.text}{child_info}",
                        'type': 'container',
                        'is_parent': False,
                        'child_count': child_count
                    })
                    logger.debug(f"Added container: {title.text}")
            
            # Extract items
            media_items = didl.findall(".//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}item")
            logger.debug(f"Found {len(media_items)} media items")
            for item in media_items:
                title = item.find(".//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}title")
                res = item.find(".//{urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/}res")
                if title is not None and res is not None:
                    # Get size and duration if available
                    size = res.get('size', '')
                    duration = res.get('duration', '')
                    size_info = f" ({self._format_size(size)})" if size else ""
                    duration_info = f" [{duration}]" if duration else ""
                    
                    items.append({
                        'id': item.get('id'),
                        'title': f"{title.text}{size_info}{duration_info}",
                        'uri': res.text,
                        'type': res.get('protocolInfo', '').split(':')[2],
                        'is_parent': False,
                        'size': size,
                        'duration': duration
                    })
                    logger.debug(f"Added media item: {title.text}")
            
            logger.info(f"Total items found: {len(items)}")
            return items
            
        except Exception as e:
            logger.error(f"Error browsing media server: {e}", exc_info=True)
            return []
    
    def _format_size(self, size_str: str) -> str:
        """Format file size in bytes to human readable format."""
        try:
            size = int(size_str)
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if size < 1024:
                    return f"{size:.1f}{unit}"
                size /= 1024
            return f"{size:.1f}PB"
        except (ValueError, TypeError):
            return ""
    
    def power_on_yamaha(self, device: upnpclient.Device) -> Tuple[bool, str]:
        """
        Power on a Yamaha device using its HTTP API.
        
        Args:
            device: The UPnP device to power on
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Extract IP address from device URL
            ip_match = re.search(r'http://([^:/]+)[:/]', device.location)
            if not ip_match:
                return False, "Could not extract IP address from device location"
            
            ip_address = ip_match.group(1)
            
            # Check if it's a Yamaha device
            if not any('yamaha' in service.service_type.lower() for service in device.services):
                return False, "Not a Yamaha device"
            
            # URL for Yamaha control API
            url = f'http://{ip_address}/YamahaRemoteControl/ctrl'
            
            # XML payload to power on the device
            payload = '''
            <YAMAHA_AV cmd="PUT">
                <Main_Zone>
                    <Power_Control>
                        <Power>On</Power>
                    </Power_Control>
                </Main_Zone>
            </YAMAHA_AV>
            '''
            
            # Send the HTTP POST request
            response = requests.post(url, data=payload.strip(), timeout=5)
            
            if response.status_code == 200:
                return True, "Power on command sent successfully"
            else:
                return False, f"Failed to send power on command. Status code: {response.status_code}"
                
        except requests.exceptions.Timeout:
            return False, "Request timed out while trying to power on device"
        except requests.exceptions.ConnectionError:
            return False, "Could not connect to device"
        except Exception as e:
            logger.error(f"Error powering on Yamaha device: {e}")
            return False, f"Error: {str(e)}"

def discover_media_servers():
    """
    Discover media servers on the network
    Returns a list of media server devices
    """
    try:
        devices = upnpclient.discover()
        media_servers = [
            {
                'friendly_name': d.friendly_name,
                'location': d.location,
                'device': d
            }
            for d in devices
            if 'MediaServer' in d.device_type
        ]
        return media_servers
    except Exception as e:
        logger.error(f"Error discovering media servers: {e}")
        return []

def discover_media_renderers():
    """
    Discover media renderers on the network
    Returns a list of media renderer devices
    """
    try:
        devices = upnpclient.discover()
        media_renderers = [
            {
                'friendly_name': d.friendly_name,
                'location': d.location,
                'device': d
            }
            for d in devices
            if 'MediaRenderer' in d.device_type
        ]
        return media_renderers
    except Exception as e:
        logger.error(f"Error discovering media renderers: {e}")
        return []
