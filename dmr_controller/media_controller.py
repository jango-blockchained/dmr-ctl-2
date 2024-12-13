import logging
from typing import Optional, List, Dict, Any, Tuple, TYPE_CHECKING, Union, cast
try:
    import upnpclient
except ImportError:
    upnpclient = None
from .discovery import DeviceDiscovery
from .receiver_controller import BaseReceiverController
from .yamaha_controller import YamahaController
import requests
from xml.etree import ElementTree
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess
import sys
import socket
import re
import time

# Try to import optional dependencies
try:
    import vlc
    VLC_AVAILABLE = True
except ImportError:
    VLC_AVAILABLE = False

try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from upnpclient import Device as UPnPDevice
else:
    UPnPDevice = Any

def check_vlc_installed():
    """Check if VLC is installed on the system."""
    try:
        if sys.platform.startswith('linux'):
            subprocess.run(['which', 'vlc'], check=True, capture_output=True)
        elif sys.platform == 'darwin':
            subprocess.run(['which', 'vlc'], check=True, capture_output=True)
        elif sys.platform == 'win32':
            subprocess.run(['where', 'vlc'], check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        return False

class AVTransportService:
    """Service class for handling AVTransport commands."""
    
    def __init__(self, location):
        self.service_type = 'urn:schemas-upnp-org:service:AVTransport:1'
        self.location = location
        base_url = '/'.join(location.split('/')[:3])
        self.control_url = f"{base_url}/MediaRenderer/AVTransport/Control"
        logger.info(f"Using AVTransport control URL: {self.control_url}")
        # Configure timeouts and retries
        self.timeout = 5  # seconds
        self.max_retries = 3
        self.retry_delay = 1  # seconds
        
    def _check_renderer_available(self) -> bool:
        """Check if the renderer is responding."""
        try:
            # Try a simple HEAD request first
            base_url = '/'.join(self.control_url.split('/')[:3])
            response = requests.head(base_url, timeout=2)
            return response.status_code == 200
        except:
            return False
        
    def _send_command(self, action: str, params: dict, extended_timeout: bool = False) -> None:
        """
        Send SOAP command to the device with retries.
        
        Args:
            action: The UPnP action to perform
            params: The parameters for the action
            extended_timeout: Whether to use extended timeouts for this command
        """
        if not self._check_renderer_available():
            raise RuntimeError("Renderer is not responding")
            
        headers = {
            'Content-Type': 'text/xml; charset="utf-8"',
            'SOAPACTION': f'"urn:schemas-upnp-org:service:AVTransport:1#{action}"'
        }
        
        # Build SOAP body
        params_xml = '\n'.join(f'<{k}>{v}</>{k}>' for k, v in params.items())
        body = f"""<?xml version="1.0"?>
        <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
            <s:Body>
                <u:{action} xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
                    {params_xml}
                </u:{action}>
            </s:Body>
        </s:Envelope>"""
        
        # Log the request details for debugging
        logger.debug(f"Sending request to: {self.control_url}")
        logger.debug(f"Headers: {headers}")
        logger.debug(f"Body length: {len(body)} bytes")
        
        # Use extended timeouts for certain operations
        timeout = (self.timeout * 2, self.timeout * 4) if extended_timeout else (self.timeout, self.timeout * 2)
        
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"Sending {action} command (attempt {attempt + 1}/{self.max_retries})")
                response = requests.post(
                    self.control_url,
                    headers=headers,
                    data=body,
                    timeout=timeout
                )
                response.raise_for_status()
                
                # Log response for debugging
                logger.debug(f"Response status: {response.status_code}")
                logger.debug(f"Response content length: {len(response.content)} bytes")
                
                return  # Success
            except requests.Timeout as e:
                last_exception = e
                logger.warning(f"Timeout on attempt {attempt + 1} for {action}: {e}")
            except requests.ConnectionError as e:
                last_exception = e
                logger.warning(f"Connection error on attempt {attempt + 1} for {action}: {e}")
            except requests.RequestException as e:
                last_exception = e
                logger.warning(f"Request error on attempt {attempt + 1} for {action}: {e}")
            
            if attempt < self.max_retries - 1:
                time.sleep(self.retry_delay * (attempt + 1))  # Exponential backoff
        
        # If we get here, all retries failed
        raise last_exception or RuntimeError(f"Failed to send {action} command after {self.max_retries} attempts")
        
    def SetAVTransportURI(self, InstanceID: int, CurrentURI: str, CurrentURIMetaData: str) -> None:
        """Set the URI for playback."""
        try:
            # Validate the URL
            if not CurrentURI.startswith(('http://', 'https://')):
                raise ValueError("Invalid URL scheme")
                
            # Check if URL is reachable
            try:
                response = requests.head(CurrentURI, timeout=2)
                response.raise_for_status()
            except:
                logger.warning(f"Media URL {CurrentURI} is not directly accessible, proceeding anyway")
            
            logger.info(f"Setting transport URI: {CurrentURI}")
            # Use extended timeout for SetAVTransportURI due to long URLs
            self._send_command('SetAVTransportURI', {
                'InstanceID': InstanceID,
                'CurrentURI': CurrentURI,
                'CurrentURIMetaData': CurrentURIMetaData
            }, extended_timeout=True)
            
            # Wait a bit longer for long URLs
            wait_time = 1.0 if len(CurrentURI) > 255 else 0.5
            time.sleep(wait_time)
            
        except Exception as e:
            logger.error(f"Error setting transport URI: {e}")
            raise
    
    def Play(self, InstanceID: int, Speed: str) -> None:
        """Start playback."""
        logger.info("Starting playback")
        self._send_command('Play', {
            'InstanceID': InstanceID,
            'Speed': Speed
        })
        
    def Pause(self, InstanceID: int) -> None:
        """Pause playback."""
        self._send_command('Pause', {
            'InstanceID': InstanceID
        })
        
    def Stop(self, InstanceID: int) -> None:
        """Stop playback."""
        self._send_command('Stop', {
            'InstanceID': InstanceID
        })
        
    def GetPositionInfo(self, InstanceID: int) -> dict:
        """Get current position information."""
        try:
            self._send_command('GetPositionInfo', {
                'InstanceID': InstanceID
            })
            return {}  # TODO: Parse response XML
        except:
            return {}
            
    def GetTransportInfo(self, InstanceID: int) -> dict:
        """Get transport state information."""
        try:
            self._send_command('GetTransportInfo', {
                'InstanceID': InstanceID
            })
            return {}  # TODO: Parse response XML
        except:
            return {}


class RenderingControlService:
    """Service class for handling RenderingControl commands."""
    
    def __init__(self, location):
        self.service_type = 'urn:schemas-upnp-org:service:RenderingControl:1'
        self.location = location
        base_url = '/'.join(location.split('/')[:3])
        self.control_url = f"{base_url}/MediaRenderer/RenderingControl/Control"
        logger.info(f"Using RenderingControl control URL: {self.control_url}")
        # Configure timeouts and retries
        self.timeout = 5  # seconds
        self.max_retries = 3
        self.retry_delay = 1  # seconds
        
    def _send_command(self, action: str, params: dict) -> None:
        """Send SOAP command to the device with retries."""
        headers = {
            'Content-Type': 'text/xml; charset="utf-8"',
            'SOAPACTION': f'"urn:schemas-upnp-org:service:RenderingControl:1#{action}"'
        }
        
        # Build SOAP body
        params_xml = '\n'.join(f'<{k}>{v}</>{k}>' for k, v in params.items())
        body = f"""<?xml version="1.0"?>
        <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
            <s:Body>
                <u:{action} xmlns:u="urn:schemas-upnp-org:service:RenderingControl:1">
                    {params_xml}
                </u:{action}>
            </s:Body>
        </s:Envelope>"""
        
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"Sending {action} command (attempt {attempt + 1}/{self.max_retries})")
                response = requests.post(
                    self.control_url,
                    headers=headers,
                    data=body,
                    timeout=(self.timeout, self.timeout * 2)  # (connect timeout, read timeout)
                )
                response.raise_for_status()
                return  # Success
            except requests.Timeout as e:
                last_exception = e
                logger.warning(f"Timeout on attempt {attempt + 1} for {action}: {e}")
            except requests.ConnectionError as e:
                last_exception = e
                logger.warning(f"Connection error on attempt {attempt + 1} for {action}: {e}")
            except requests.RequestException as e:
                last_exception = e
                logger.warning(f"Request error on attempt {attempt + 1} for {action}: {e}")
            
            if attempt < self.max_retries - 1:
                time.sleep(self.retry_delay)
        
        # If we get here, all retries failed
        raise last_exception or RuntimeError(f"Failed to send {action} command after {self.max_retries} attempts")
    
    def SetVolume(self, InstanceID: int, Channel: str, DesiredVolume: int) -> None:
        """Set the volume level."""
        self._send_command('SetVolume', {
            'InstanceID': InstanceID,
            'Channel': Channel,
            'DesiredVolume': DesiredVolume
        })


class MediaController:
    """Controls media playback and device operations."""
    
    def __init__(self):
        self.discovery = DeviceDiscovery()
        self._current_renderer: Optional[UPnPDevice] = None
        self._current_server: Optional[UPnPDevice] = None
        self.current_media_url: Optional[str] = None
        self._av_transport: Optional[Any] = None
        self._rendering_control: Optional[Any] = None
        self.receiver: Optional[BaseReceiverController] = None
        
        # Initialize VLC if available
        self.instance = None
        self.player = None
        
        if not VLC_AVAILABLE:
            logger.warning("python-vlc package is not installed. Local playback will be disabled.")
            return
            
        if not check_vlc_installed():
            logger.warning("VLC media player is not installed on the system. Please install it first.")
            if sys.platform.startswith('linux'):
                logger.info("You can install VLC using: sudo apt-get install vlc")
            return
            
        try:
            self.instance = vlc.Instance()
            if self.instance is None:
                logger.error("Failed to create VLC instance")
                self.player = None
                return
                
            self.player = self.instance.media_player_new()
            if self.player is None:
                logger.error("Failed to create VLC media player")
                return
                
            logger.info("VLC initialized successfully")
        except AttributeError as e:
            logger.error(f"Failed to initialize VLC: {e}")
            self.instance = None
            self.player = None
        except Exception as e:
            logger.error(f"An unexpected error occurred while initializing VLC: {e}")
            self.instance = None
            self.player = None

    @property
    def current_renderer(self) -> Optional[UPnPDevice]:
        """Get current renderer."""
        return self._current_renderer
    
    @current_renderer.setter
    def current_renderer(self, value: Optional[Union[UPnPDevice, Dict[str, Any]]]) -> None:
        """Set current renderer.
        
        Args:
            value: The renderer device to set, can be a UPnPDevice or a dict with device info
        """
        if value is None:
            self._current_renderer = None
            return
            
        # If it's a dict, convert it to match UPnPDevice interface
        if isinstance(value, dict):
            class DictWrapper:
                def __init__(self, data: Dict[str, Any]):
                    self.location = data.get('location', '')
                    self.device_type = data.get('device_type', '')
                    self.friendly_name = data.get('friendly_name', '')
                    
            self._current_renderer = cast(UPnPDevice, DictWrapper(value))
        else:
            self._current_renderer = cast(UPnPDevice, value)
    
    @property
    def current_server(self) -> Optional[UPnPDevice]:
        """Get current server."""
        return self._current_server
    
    @current_server.setter
    def current_server(self, value: Optional[UPnPDevice]):
        """Set current server."""
        self._current_server = value

    def set_renderer(self, renderer) -> bool:
        """
        Set the current media renderer device.
        
        Args:
            renderer: The UPnP device to use as renderer
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Get renderer location and info
            if isinstance(renderer, dict):
                location = renderer.get('location', '')
                device_type = renderer.get('device_type', '').lower()
                manufacturer = renderer.get('manufacturer', '').lower()
            else:
                location = getattr(renderer, 'location', '')
                device_type = getattr(renderer, 'device_type', '').lower()
                manufacturer = getattr(renderer, 'manufacturer', '').lower()
            
            if not location:
                logger.error("Renderer location URL is required")
                return False

            # Try to set up specific receiver controller
            if 'yamaha' in manufacturer:
                try:
                    self.receiver = YamahaController(location.split('/')[2])  # Extract IP from URL
                    logger.info("Initialized Yamaha controller")
                    return True
                except Exception as e:
                    logger.error(f"Failed to initialize Yamaha controller: {e}")
                    self.receiver = None
            
            # Fall back to generic DLNA control
            self.current_renderer = renderer  # Use property setter
            self._setup_av_transport()
            logger.info("Using generic DLNA control")
            return True
            
        except Exception as e:
            logger.error(f"Error setting renderer: {e}")
            self.current_renderer = None  # Use property setter
            self._av_transport = None
            self._rendering_control = None
            self.receiver = None
            return False

    def _setup_av_transport(self):
        """Set up AVTransport and RenderingControl services."""
        try:
            # Get renderer location
            if isinstance(self.current_renderer, dict):
                location = self.current_renderer.get('location', '')
                device_type = self.current_renderer.get('device_type', '').lower()
            else:
                location = getattr(self.current_renderer, 'location', '')
                device_type = getattr(self.current_renderer, 'device_type', '').lower()
            
            if not location:
                logger.error("Renderer location URL is required")
                return False
            
            # Create services list with both services
            self.services = [
                AVTransportService(location),
                RenderingControlService(location)
            ]
            
            self._av_transport = next(
                (service for service in self.services 
                 if 'AVTransport' in service.service_type),
                None
            )
            self._rendering_control = next(
                (service for service in self.services 
                 if 'RenderingControl' in service.service_type),
                None
            )
            
            if not self._av_transport or not self._rendering_control:
                logger.error("Required services not found")
                return False
            
            logger.info(f"Successfully set media renderer at {location}")
            return True
            
        except Exception as e:
            logger.error(f"Error setting renderer: {e}", exc_info=True)
            return False
    
    def _get_device_description(self, location: str) -> Optional[Dict]:
        """Get device description from its location URL."""
        try:
            response = requests.get(location, timeout=5)
            response.raise_for_status()
            
            root = ElementTree.fromstring(response.text)
            ns = {'ns': 'urn:schemas-upnp-org:device-1-0'}
            
            # Get device info
            device = root.find('.//ns:device', ns)
            if device is not None:
                device_type = device.find('ns:deviceType', ns)
                friendly_name = device.find('ns:friendlyName', ns)
                
                # Find ContentDirectory service
                content_directory = None
                for service in device.findall('.//ns:service', ns):
                    service_type = service.find('ns:serviceType', ns)
                    service_type_text = service_type.text if service_type is not None else ''
                    if service_type_text and 'ContentDirectory' in service_type_text:
                        control_url = service.find('ns:controlURL', ns)
                        if control_url is not None:
                            content_directory = {
                                'type': service_type_text,
                                'control_url': control_url.text if control_url.text is not None else ''
                            }
                            break
                
                return {
                    'device_type': device_type.text if device_type is not None else 'urn:schemas-upnp-org:device:MediaServer:1',
                    'friendly_name': friendly_name.text if friendly_name is not None else 'Unknown Server',
                    'content_directory': content_directory
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting device description: {e}", exc_info=True)
            return None

    def set_server(self, server) -> bool:
        """
        Set the current media server device.
        
        Args:
            server: The UPnP device to use as media server (can be dict or Device object)
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Get server location
            if isinstance(server, dict):
                location = server.get('location', '')
            else:
                location = getattr(server, 'location', '')
            
            if not location:
                logger.error("Server location URL is required")
                return False
            
            # Get device description
            device_info = self._get_device_description(location)
            if not device_info:
                logger.error("Could not get device description")
                return False
            
            # Create device wrapper
            class DeviceWrapper:
                """Wrapper for UPnP devices with content directory service."""
                
                def __init__(self, location: str, device_info: Dict):
                    self.device_type = device_info['device_type']
                    self.friendly_name = device_info['friendly_name']
                    self.location = location
                    self._content_directory = None  # Initialize as None
                    
                    # Create ContentDirectory service
                    class ServiceWrapper:
                        def __init__(self, location: str, content_directory: Optional[Dict]):
                            self.service_type = 'urn:schemas-upnp-org:service:ContentDirectory:1'
                            self.location = location
                            
                            # Set control URL
                            if content_directory and content_directory.get('control_url'):
                                base_url = '/'.join(location.split('/')[:3])
                                self.control_url = base_url + content_directory['control_url']
                                logger.info(f"Using discovered control URL: {self.control_url}")
                            elif 'rygel' in location.lower():
                                base_url = '/'.join(location.split('/')[:3])
                                self.control_url = f"{base_url}/Control/MediaExport/RygelContentDirectory"
                                logger.info(f"Using Rygel-specific control URL: {self.control_url}")
                            else:
                                base_url = '/'.join(location.split('/')[:3])
                                self.control_url = f"{base_url}/MediaServer/ContentDirectory/Control"
                                logger.info(f"Using default control URL: {self.control_url}")
                        
                        def Browse(self, ObjectID, BrowseFlag, Filter, StartingIndex, RequestedCount, SortCriteria):
                            """Browse the content directory."""
                            try:
                                # Construct the SOAP request
                                headers = {
                                    'Content-Type': 'text/xml; charset="utf-8"',
                                    'SOAPACTION': '"urn:schemas-upnp-org:service:ContentDirectory:1#Browse"'
                                }
                                
                                body = f"""<?xml version="1.0"?>
                                <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                                    <s:Body>
                                        <u:Browse xmlns:u="urn:schemas-upnp-org:service:ContentDirectory:1">
                                            <ObjectID>{ObjectID}</ObjectID>
                                            <BrowseFlag>{BrowseFlag}</BrowseFlag>
                                            <Filter>{Filter}</Filter>
                                            <StartingIndex>{StartingIndex}</StartingIndex>
                                            <RequestedCount>{RequestedCount}</RequestedCount>
                                            <SortCriteria>{SortCriteria}</SortCriteria>
                                        </u:Browse>
                                    </s:Body>
                                </s:Envelope>"""
                                
                                # Send the SOAP request
                                response = requests.post(self.control_url, headers=headers, data=body, timeout=10)
                                response.raise_for_status()
                                
                                # Parse the response
                                root = ElementTree.fromstring(response.text)
                                browse_response = root.find('.//{*}BrowseResponse')
                                
                                if browse_response is not None:
                                    result = browse_response.find('{*}Result')
                                    number_returned = browse_response.find('{*}NumberReturned')
                                    total_matches = browse_response.find('{*}TotalMatches')
                                    update_id = browse_response.find('{*}UpdateID')
                                    
                                    return {
                                        'Result': result.text if result is not None else '',
                                        'NumberReturned': int(number_returned.text) if number_returned is not None and number_returned.text is not None else 0,
                                        'TotalMatches': int(total_matches.text) if total_matches is not None and total_matches.text is not None else 0,
                                        'UpdateID': int(update_id.text) if update_id is not None and update_id.text is not None else 0
                                    }
                                
                                logger.error("Invalid SOAP response format")
                                return {
                                    'Result': '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"></DIDL-Lite>',
                                    'NumberReturned': 0,
                                    'TotalMatches': 0,
                                    'UpdateID': 0
                                }
                                
                            except Exception as e:
                                logger.error(f"Error browsing content directory: {e}", exc_info=True)
                                return {
                                    'Result': '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"></DIDL-Lite>',
                                    'NumberReturned': 0,
                                    'TotalMatches': 0,
                                    'UpdateID': 0
                                }
                    
                    # Create services list and expose content_directory
                    self.services = [ServiceWrapper(location, device_info.get('content_directory'))]
                    self._content_directory = self.services[0]  # Store service instance
                
                @property
                def content_directory(self):
                    """Get content directory service."""
                    return self._content_directory
            
            # Create server instance
            server_wrapper = DeviceWrapper(location, device_info)
            
            # Get device type
            device_type = device_info['device_type'].lower()
            
            # Log the server information
            logger.info(f"Setting up media server:")
            logger.info(f"  Type: {device_type}")
            logger.info(f"  Name: {device_info['friendly_name']}")
            logger.info(f"  Location: {location}")
            
            # Check if it's a media server
            if 'mediaserver' in device_type or 'contentdirectory' in device_type:
                self._current_server = cast(UPnPDevice, server_wrapper)  # Cast to satisfy type checker
                logger.info(f"Successfully set media server: {device_info['friendly_name']}")
                return True
            
            logger.error(f"Invalid device type: {device_type}")
            return False
            
        except Exception as e:
            logger.error(f"Error setting media server: {e}", exc_info=True)
            return False
    
    def play(self, media_url: Optional[str] = None) -> bool:
        """
        Start or resume media playback.
        
        Args:
            media_url: Optional URL of media to play. If None, resumes current media
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.current_renderer or not self._av_transport:
            logger.error("No renderer selected or AVTransport service not available")
            return False
            
        try:
            if media_url:
                self.current_media_url = media_url
                # Set AV Transport URI and play
                self._av_transport.SetAVTransportURI(
                    InstanceID=0,
                    CurrentURI=media_url,
                    CurrentURIMetaData=""
                )
            
            self._av_transport.Play(InstanceID=0, Speed="1")
            return True
        except Exception as e:
            logger.error(f"Error during playback: {e}")
            return False
    
    def pause(self) -> bool:
        """
        Pause media playback.
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.current_renderer or not self._av_transport:
            logger.error("No renderer selected or AVTransport service not available")
            return False
            
        try:
            self._av_transport.Pause(InstanceID=0)
            return True
        except Exception as e:
            logger.error(f"Error pausing playback: {e}")
            return False
    
    def stop(self) -> bool:
        """
        Stop media playback.
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.current_renderer or not self._av_transport:
            logger.error("No renderer selected or AVTransport service not available")
            return False
            
        try:
            self._av_transport.Stop(InstanceID=0)
            return True
        except Exception as e:
            logger.error(f"Error stopping playback: {e}")
            return False
    
    def set_volume(self, volume: int) -> bool:
        """
        Set the playback volume.
        
        Args:
            volume: Volume level (0-100)
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.current_renderer or not self._rendering_control:
            logger.error("No renderer selected or RenderingControl service not available")
            return False
            
        try:
            # Ensure volume is within valid range
            volume = max(0, min(100, volume))
            
            self._rendering_control.SetVolume(
                InstanceID=0,
                Channel='Master',
                DesiredVolume=volume
            )
            return True
        except Exception as e:
            logger.error(f"Error setting volume: {e}")
            return False
    
    def get_position_info(self) -> Optional[dict]:
        """
        Get current playback position information.
        
        Returns:
            dict: Position information if successful, None otherwise
        """
        if not self.current_renderer or not self._av_transport:
            logger.error("No renderer selected or AVTransport service not available")
            return None
            
        try:
            return self._av_transport.GetPositionInfo(InstanceID=0)
        except Exception as e:
            logger.error(f"Error getting position info: {e}")
            return None
    
    def get_transport_info(self) -> Optional[dict]:
        """
        Get current transport state information.
        
        Returns:
            dict: Transport information if successful, None otherwise
        """
        if not self.current_renderer or not self._av_transport:
            logger.error("No renderer selected or AVTransport service not available")
            return None
            
        try:
            return self._av_transport.GetTransportInfo(InstanceID=0)
        except Exception as e:
            logger.error(f"Error getting transport info: {e}")
            return None
    
    def browse_media_server(self, server_url: str, object_id: str = "0") -> List[Dict]:
        """
        Browse content from a media server.
        
        Args:
            server_url: The URL of the media server
            object_id: The ID of the object to browse (default is root "0")
            
        Returns:
            List of media items with their metadata
        """
        try:
            if not self.current_server:
                logger.error("No media server currently set")
                return []
            
            # Use DeviceDiscovery's implementation
            return self.discovery.browse_media_server(self.current_server, object_id)
            
        except Exception as e:
            logger.error(f"Error browsing media server: {e}", exc_info=True)
            return []
    
    def browse_local_file(self):
        """Open file dialog to browse and select local media files"""
        if not VLC_AVAILABLE:
            messagebox.showerror(
                "Error",
                "VLC is not installed. Please install python-vlc package to enable local playback:\n"
                "pip install python-vlc"
            )
            return
            
        if not self.instance or not self.player:
            messagebox.showerror(
                "Error",
                "VLC player is not initialized. Please install VLC media player."
            )
            return
            
        filetypes = (
            ('Audio Files', '*.mp3 *.wav *.flac *.m4a *.aac'),
            ('Video Files', '*.mp4 *.mkv *.avi *.mov'),
            ('All Files', '*.*')
        )
        
        file_path = filedialog.askopenfilename(
            title='Select a media file',
            filetypes=filetypes
        )
        
        if file_path:
            self.play_local_file(file_path)
            
    def play_local_file(self, file_path: str) -> bool:
        """Play a local media file"""
        if not VLC_AVAILABLE or not self.instance or not self.player:
            messagebox.showerror(
                "Error",
                "VLC is not properly initialized. Please check your installation."
            )
            return False
            
        try:
            media = self.instance.media_new(file_path)
            self.player.set_media(media)
            self.player.play()
            logger.info(f"Playing local file: {file_path}")
            return True
        except Exception as e:
            error_msg = f"Error playing local file: {e}"
            logger.error(error_msg)
            messagebox.showerror("Error", error_msg)
            return False
    
    def play_soundcloud(self, url: str) -> bool:
        """Download and play a Soundcloud track"""
        if not YTDLP_AVAILABLE:
            messagebox.showerror(
                "Error",
                "yt-dlp is not installed. Please install it to enable Soundcloud downloads:\n"
                "pip install yt-dlp"
            )
            return False
            
        if not VLC_AVAILABLE or not self.instance or not self.player:
            messagebox.showerror(
                "Error",
                "VLC is not properly initialized. Please check your installation."
            )
            return False
            
        try:
            # Create downloads directory if it doesn't exist
            downloads_dir = Path('downloads')
            downloads_dir.mkdir(exist_ok=True)
            
            # Configure yt-dlp options
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': str(downloads_dir / '%(title)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            }
            
            # Download the track
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info(f"Downloading from URL: {url}")
                info = ydl.extract_info(url, download=True)
                if not info or 'title' not in info:
                    raise ValueError("Failed to get track information from URL")
                    
                downloaded_file = downloads_dir / f"{info['title']}.mp3"
                
                if not downloaded_file.exists():
                    raise FileNotFoundError(f"Downloaded file not found: {downloaded_file}")
                
                logger.info(f"Successfully downloaded: {downloaded_file}")
                return self.play_local_file(str(downloaded_file))
                
        except Exception as e:
            error_msg = f"Error downloading/playing Soundcloud track: {e}"
            logger.error(error_msg)
            messagebox.showerror("Error", error_msg)
            return False
    
    def get_media_info(self) -> Optional[dict]:
        """Get current media information."""
        if not self.current_renderer:
            return None
            
        try:
            # Get IP from renderer location
            ip_match = re.search(r'http://([^:/]+)[:/]', self.current_renderer.location)
            if not ip_match:
                return None
                
            ip = ip_match.group(1)
            
            # URL for Yamaha control API
            url = f'http://{ip}/YamahaRemoteControl/ctrl'
            
            # XML payload to get playback info
            payload = '''
            <YAMAHA_AV cmd="GET">
                <Main_Zone>
                    <Basic_Status>GetParam</Basic_Status>
                </Main_Zone>
            </YAMAHA_AV>
            '''
            
            # Send the command with a short timeout
            response = requests.post(url, data=payload, timeout=1)
            
            if response.status_code == 200:
                # Parse XML response
                xml = ElementTree.fromstring(response.content)
                
                # Extract playback info
                power = xml.find('.//Power')
                input_sel = xml.find('.//Input_Sel')
                volume = xml.find('.//Volume/Lvl/Val')
                mute = xml.find('.//Volume/Mute')
                
                # Get current input name as title
                title = input_sel.text if input_sel is not None else 'Unknown'
                
                # Get power state
                state = 'PLAYING' if power is not None and power.text == 'On' else 'STOPPED'
                
                # Get volume level
                vol_level = volume.text if volume is not None else '0'
                
                # Get mute state
                is_muted = mute is not None and mute.text == 'On'
                
                return {
                    'title': title,
                    'artist': 'Yamaha Receiver',
                    'album': '',
                    'duration': '00:00:00',
                    'position': '00:00:00',
                    'state': state,
                    'volume': vol_level,
                    'mute': is_muted,
                    'uri': ''
                }
                
            return None
                
        except requests.exceptions.Timeout:
            logger.debug("Timeout getting media info")
            return None
        except requests.exceptions.RequestException as e:
            logger.debug(f"Network error getting media info: {e}")
            return None
        except Exception as e:
            logger.debug(f"Error getting media info: {e}")
            return None
    
    def get_receiver_status(self) -> Dict[str, Any]:
        """Get current status of the receiver."""
        if self.receiver:
            return self.receiver.get_status()
        return {}
        
    def set_receiver_power(self, power: bool) -> bool:
        """Control receiver power."""
        if self.receiver:
            return self.receiver.set_power(power)
        return False
        
    def set_receiver_volume(self, volume: int) -> bool:
        """Set receiver volume (0-100)."""
        if self.receiver:
            return bool(self.receiver.set_volume(volume))
        return False
        
    def set_receiver_input(self, input_source: str) -> bool:
        """Set receiver input source."""
        if self.receiver:
            return self.receiver.set_input(input_source)
        return False
        
    def get_receiver_inputs(self) -> List[str]:
        """Get list of available receiver inputs."""
        if self.receiver:
            return self.receiver.get_input_list()
        return []
        
    def set_receiver_mute(self, mute: bool) -> bool:
        """Set receiver mute state."""
        if self.receiver:
            return self.receiver.set_mute(mute)
        return False
    
    def browse_container(self, container_id: str) -> Optional[List[Dict[str, Any]]]:
        """Browse a container on the current media server.
        
        Args:
            container_id: ID of the container to browse
            
        Returns:
            List of items in the container, each item being a dict with:
                - id: Item ID
                - title: Item title
                - type: 'container' or 'item'
                - url: URL for items (None for containers)
        """
        if not self.current_server:
            logger.warning("No media server selected")
            return None
            
        try:
            content_directory = self.current_server.content_directory
            if not content_directory:
                logger.error("No content directory service available")
                return None
                
            # Browse the container
            result = content_directory.Browse(
                ObjectID=container_id,
                BrowseFlag='BrowseDirectChildren',
                Filter='*',
                StartingIndex=0,
                RequestedCount=0,
                SortCriteria=''
            )
            
            if not result:
                logger.warning(f"No results from browsing container {container_id}")
                return None
                
            # Parse DIDL-Lite XML
            from xml.etree import ElementTree as ET
            didl = result['Result']
            root = ET.fromstring(didl)
            
            # Define namespace mapping
            ns = {
                'didl': 'urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/',
                'upnp': 'urn:schemas-upnp-org:metadata-1-0/upnp/',
                'dc': 'http://purl.org/dc/elements/1.1/'
            }
            
            items = []
            for item in root.findall('.//didl:item', ns) + root.findall('.//didl:container', ns):
                try:
                    item_id = item.get('id')
                    title = item.find('dc:title', ns)
                    title_text = title.text if title is not None else 'Unknown'
                    
                    # Determine if it's a container or item
                    is_container = item.tag.endswith('container')
                    
                    item_dict = {
                        'id': item_id,
                        'title': title_text,
                        'type': 'container' if is_container else 'item'
                    }
                    
                    # For items, get the resource URL
                    if not is_container:
                        res = item.find('didl:res', ns)
                        if res is not None:
                            item_dict['url'] = res.text
                    
                    items.append(item_dict)
                except Exception as e:
                    logger.error(f"Error parsing item: {e}")
                    continue
            
            return items
            
        except Exception as e:
            logger.error(f"Error browsing container: {e}")
            return None
