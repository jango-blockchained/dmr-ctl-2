import logging
from typing import Optional, List, Dict
try:
    import upnpclient
except ImportError:
    upnpclient = None
from .discovery import DeviceDiscovery
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

class MediaController:
    """Controls media playback and device operations."""
    
    def __init__(self):
        self.discovery = DeviceDiscovery()
        self.current_renderer: Optional[upnpclient.Device] = None
        self.current_server: Optional[upnpclient.Device] = None
        self.current_media_url: Optional[str] = None
        self._av_transport = None
        self._rendering_control = None
        
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
            self.player = self.instance.media_player_new()
            logger.info("VLC initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize VLC: {e}")
            self.instance = None
            self.player = None

    def set_renderer(self, renderer) -> bool:
        """
        Set the current media renderer device.
        
        Args:
            renderer: The UPnP device to use as renderer
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Get renderer location
            if isinstance(renderer, dict):
                location = renderer.get('location', '')
                device_type = renderer.get('device_type', '').lower()
            else:
                location = getattr(renderer, 'location', '')
                device_type = getattr(renderer, 'device_type', '').lower()
            
            if not location:
                logger.error("Renderer location URL is required")
                return False
            
            # Create renderer wrapper
            class DeviceWrapper:
                def __init__(self, location: str):
                    self.location = location
                    self.device_type = 'urn:schemas-upnp-org:device:MediaRenderer:1'
                    
                    # Create AVTransport service
                    class AVTransportService:
                        def __init__(self, location):
                            self.service_type = 'urn:schemas-upnp-org:service:AVTransport:1'
                            self.location = location
                            base_url = '/'.join(location.split('/')[:3])
                            self.control_url = f"{base_url}/MediaRenderer/AVTransport/Control"
                            logger.info(f"Using AVTransport control URL: {self.control_url}")
                        
                        def _send_command(self, action: str, params: Dict = None) -> Dict:
                            """Send SOAP command to AVTransport service."""
                            try:
                                # Build parameters XML
                                params_xml = ""
                                if params:
                                    for key, value in params.items():
                                        params_xml += f"<{key}>{value}</{key}>"
                                
                                # Construct SOAP request
                                headers = {
                                    'Content-Type': 'text/xml; charset="utf-8"',
                                    'SOAPACTION': f'"urn:schemas-upnp-org:service:AVTransport:1#{action}"',
                                    'Connection': 'keep-alive'
                                }
                                
                                body = f"""<?xml version="1.0"?>
                                <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                                    <s:Body>
                                        <u:{action} xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
                                            {params_xml}
                                        </u:{action}>
                                    </s:Body>
                                </s:Envelope>"""
                                
                                # Create a session for connection pooling
                                session = requests.Session()
                                
                                # Configure timeouts and retries
                                retries = 3
                                for attempt in range(retries):
                                    try:
                                        # Send request with shorter timeout
                                        response = session.post(
                                            self.control_url,
                                            headers=headers,
                                            data=body,
                                            timeout=(3, 5)  # (connect timeout, read timeout)
                                        )
                                        response.raise_for_status()
                                        return {'success': True}
                                    except requests.Timeout:
                                        if attempt < retries - 1:
                                            logger.warning(f"Timeout on attempt {attempt + 1}/{retries}, retrying...")
                                            continue
                                        raise
                                    except requests.RequestException as e:
                                        if attempt < retries - 1:
                                            logger.warning(f"Request failed on attempt {attempt + 1}/{retries}: {e}, retrying...")
                                            continue
                                        raise
                                    finally:
                                        session.close()
                                
                                return {'success': False, 'error': 'All retries failed'}
                                
                            except Exception as e:
                                logger.error(f"Error sending AVTransport command {action}: {e}")
                                return {'success': False, 'error': str(e)}
                        
                        def SetAVTransportURI(self, InstanceID: int, CurrentURI: str, CurrentURIMetaData: str = "") -> Dict:
                            """Set the URI for playback."""
                            logger.info(f"Setting AVTransport URI: {CurrentURI}")
                            result = self._send_command('SetAVTransportURI', {
                                'InstanceID': str(InstanceID),
                                'CurrentURI': CurrentURI,
                                'CurrentURIMetaData': CurrentURIMetaData
                            })
                            
                            if not result.get('success'):
                                logger.error(f"Failed to set transport URI: {result.get('error')}")
                                return result
                            
                            # Wait a bit for the URI to be set
                            time.sleep(0.5)
                            return result
                        
                        def Play(self, InstanceID: int, Speed: str = "1") -> Dict:
                            """Start playback."""
                            logger.info("Starting playback")
                            result = self._send_command('Play', {
                                'InstanceID': str(InstanceID),
                                'Speed': Speed
                            })
                            
                            if not result.get('success'):
                                logger.error(f"Failed to start playback: {result.get('error')}")
                            return result
                        
                        def Pause(self, InstanceID: int) -> Dict:
                            """Pause playback."""
                            logger.info("Pausing playback")
                            return self._send_command('Pause', {
                                'InstanceID': str(InstanceID)
                            })
                        
                        def Stop(self, InstanceID: int) -> Dict:
                            """Stop playback."""
                            logger.info("Stopping playback")
                            return self._send_command('Stop', {
                                'InstanceID': str(InstanceID)
                            })
                        
                        def Seek(self, InstanceID: int, Unit: str, Target: str) -> Dict:
                            """Seek to position."""
                            logger.info(f"Seeking to {Target} ({Unit})")
                            return self._send_command('Seek', {
                                'InstanceID': str(InstanceID),
                                'Unit': Unit,
                                'Target': Target
                            })
                        
                        def GetPositionInfo(self, InstanceID: int) -> Dict:
                            """Get current position information."""
                            try:
                                result = self._send_command('GetPositionInfo', {
                                    'InstanceID': str(InstanceID)
                                })
                                if result.get('success'):
                                    return {
                                        'Track': 0,
                                        'TrackDuration': '00:00:00',
                                        'TrackMetaData': '',
                                        'TrackURI': '',
                                        'RelTime': '00:00:00',
                                        'AbsTime': '00:00:00',
                                        'RelCount': 0,
                                        'AbsCount': 0
                                    }
                                return {}
                            except Exception as e:
                                logger.error(f"Error getting position info: {e}")
                                return {}
                        
                        def GetTransportInfo(self, InstanceID: int) -> Dict:
                            """Get transport state information."""
                            try:
                                result = self._send_command('GetTransportInfo', {
                                    'InstanceID': str(InstanceID)
                                })
                                if result.get('success'):
                                    return {
                                        'CurrentTransportState': 'STOPPED',
                                        'CurrentTransportStatus': 'OK',
                                        'CurrentSpeed': '1'
                                    }
                                return {}
                            except Exception as e:
                                logger.error(f"Error getting transport info: {e}")
                                return {}
                    
                    # Create RenderingControl service
                    class RenderingControlService:
                        def __init__(self, location):
                            self.service_type = 'urn:schemas-upnp-org:service:RenderingControl:1'
                            self.location = location
                            base_url = '/'.join(location.split('/')[:3])
                            self.control_url = f"{base_url}/MediaRenderer/RenderingControl/Control"
                            logger.info(f"Using RenderingControl control URL: {self.control_url}")
                        
                        def _send_command(self, action: str, params: Dict = None) -> Dict:
                            """Send SOAP command to RenderingControl service."""
                            try:
                                # Build parameters XML
                                params_xml = ""
                                if params:
                                    for key, value in params.items():
                                        params_xml += f"<{key}>{value}</{key}>"
                                
                                # Construct SOAP request
                                headers = {
                                    'Content-Type': 'text/xml; charset="utf-8"',
                                    'SOAPACTION': f'"urn:schemas-upnp-org:service:RenderingControl:1#{action}"'
                                }
                                
                                body = f"""<?xml version="1.0"?>
                                <s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
                                    <s:Body>
                                        <u:{action} xmlns:u="urn:schemas-upnp-org:service:RenderingControl:1">
                                            {params_xml}
                                        </u:{action}>
                                    </s:Body>
                                </s:Envelope>"""
                                
                                # Send request
                                response = requests.post(self.control_url, headers=headers, data=body, timeout=10)
                                response.raise_for_status()
                                
                                return {'success': True}
                            except Exception as e:
                                logger.error(f"Error sending RenderingControl command {action}: {e}")
                                return {'success': False, 'error': str(e)}
                        
                        def SetVolume(self, InstanceID: int, Channel: str, DesiredVolume: int) -> Dict:
                            """Set the volume level."""
                            logger.info(f"Setting volume to {DesiredVolume}")
                            return self._send_command('SetVolume', {
                                'InstanceID': str(InstanceID),
                                'Channel': Channel,
                                'DesiredVolume': str(DesiredVolume)
                            })
                    
                    # Create services list with properly instantiated services
                    self.services = [
                        AVTransportService(location),
                        RenderingControlService(location)
                    ]
            
            # Create renderer instance
            renderer = DeviceWrapper(location)
            
            # Find the services
            self._av_transport = next(
                (service for service in renderer.services 
                 if 'AVTransport' in service.service_type),
                None
            )
            self._rendering_control = next(
                (service for service in renderer.services 
                 if 'RenderingControl' in service.service_type),
                None
            )
            
            if not self._av_transport or not self._rendering_control:
                logger.error("Required services not found")
                return False
            
            self.current_renderer = renderer
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
                    if service_type is not None and 'ContentDirectory' in service_type.text:
                        control_url = service.find('ns:controlURL', ns)
                        if control_url is not None:
                            content_directory = {
                                'type': service_type.text,
                                'control_url': control_url.text
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
                def __init__(self, location: str, device_info: Dict):
                    self.device_type = device_info['device_type']
                    self.friendly_name = device_info['friendly_name']
                    self.location = location
                    
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
                                        'NumberReturned': int(number_returned.text) if number_returned is not None else 0,
                                        'TotalMatches': int(total_matches.text) if total_matches is not None else 0,
                                        'UpdateID': int(update_id.text) if update_id is not None else 0
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
                    
                    self.services = [ServiceWrapper(location, device_info.get('content_directory'))]
            
            # Create server instance
            server = DeviceWrapper(location, device_info)
            device_type = server.device_type.lower()
            
            # Log the server information
            logger.info(f"Setting up media server:")
            logger.info(f"  Type: {device_type}")
            logger.info(f"  Name: {server.friendly_name}")
            logger.info(f"  Location: {server.location}")
            
            # Check if it's a media server
            if 'mediaserver' in device_type or 'contentdirectory' in device_type:
                self.current_server = server
                logger.info(f"Successfully set media server: {server.friendly_name}")
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
    
    def get_input_sources(self) -> Optional[List[str]]:
        """Get available input sources for Yamaha receiver."""
        try:
            if not self.current_renderer:
                logger.error("No renderer selected")
                return None
                
            # Common Yamaha input sources
            sources = [
                'HDMI1', 'HDMI2', 'HDMI3', 'HDMI4', 'HDMI5',
                'AV1', 'AV2', 'AV3', 'AV4', 'AV5', 'AV6',
                'AUDIO1', 'AUDIO2', 'AUDIO3',
                'TUNER', 'PHONO', 'CD',
                'NET RADIO', 'SERVER', 'NAPSTER',
                'SPOTIFY', 'BLUETOOTH', 'USB',
                'AirPlay'
            ]
            return sources
        except Exception as e:
            logger.error(f"Error getting input sources: {e}")
            return None
    
    def set_input_source(self, source: str) -> bool:
        """Set the input source for Yamaha receiver."""
        try:
            if not self.current_renderer:
                logger.error("No renderer selected")
                return False
                
            # Get IP from renderer location
            ip_match = re.search(r'http://([^:/]+)[:/]', self.current_renderer.location)
            if not ip_match:
                logger.error("Could not extract IP address from renderer location")
                return False
                
            ip = ip_match.group(1)
            
            # URL for Yamaha control API
            url = f'http://{ip}/YamahaRemoteControl/ctrl'
            
            # XML payload for input selection
            payload = f'''
            <YAMAHA_AV cmd="PUT">
                <Main_Zone>
                    <Input>
                        <Input_Sel>{source}</Input_Sel>
                    </Input>
                </Main_Zone>
            </YAMAHA_AV>
            '''
            
            # Send the command
            response = requests.post(url, data=payload, timeout=5)
            
            if response.status_code == 200:
                logger.info(f"Successfully changed input to {source}")
                return True
            else:
                logger.error(f"Failed to change input. Status code: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error setting input source: {e}")
            return False
    
    def get_current_input(self) -> Optional[str]:
        """Get the current input source from Yamaha receiver."""
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
            
            # XML payload to get current input
            payload = '''
            <YAMAHA_AV cmd="GET">
                <Main_Zone>
                    <Input>
                        <Input_Sel>GetParam</Input_Sel>
                    </Input>
                </Main_Zone>
            </YAMAHA_AV>
            '''
            
            # Send the command with a short timeout
            response = requests.post(url, data=payload, timeout=1)
            
            if response.status_code == 200:
                # Parse XML response to get current input
                xml = ElementTree.fromstring(response.content)
                input_sel = xml.find('.//Input_Sel')
                if input_sel is not None:
                    return input_sel.text
                    
            return None
                
        except requests.exceptions.Timeout:
            logger.debug("Timeout getting current input")
            return None
        except requests.exceptions.RequestException as e:
            logger.debug(f"Network error getting current input: {e}")
            return None
        except Exception as e:
            logger.debug(f"Error getting current input: {e}")
            return None
    
    def power_on(self, ip: str) -> bool:
        """
        Send power on command to the Yamaha receiver.
        
        Args:
            ip: IP address of the receiver
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # URL for Yamaha receiver control
            url = f'http://{ip}/YamahaRemoteControl/ctrl'
            
            # XML payload for power on
            payload = '''
            <YAMAHA_AV cmd="PUT">
                <Main_Zone>
                    <Power_Control>
                        <Power>On</Power>
                    </Power_Control>
                </Main_Zone>
            </YAMAHA_AV>
            '''
            
            # Send the command
            response = requests.post(url, data=payload, timeout=5)
            
            if response.status_code == 200:
                logger.info(f"Successfully sent power on command to {ip}")
                return True
            else:
                logger.error(f"Failed to send power on command. Status code: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error powering on device: {e}")
            return False
    
    def power_off(self, ip: str) -> bool:
        """
        Send power off command to the Yamaha receiver.
        
        Args:
            ip: IP address of the receiver
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Try to stop playback first
            try:
                self.stop()
            except:
                pass
            
            # URL for Yamaha receiver control
            url = f'http://{ip}/YamahaRemoteControl/ctrl'
            
            # XML payload for power off
            payload = '''
            <YAMAHA_AV cmd="PUT">
                <Main_Zone>
                    <Power_Control>
                        <Power>Standby</Power>
                    </Power_Control>
                </Main_Zone>
            </YAMAHA_AV>
            '''
            
            # Send the command
            response = requests.post(url, data=payload, timeout=5)
            
            if response.status_code == 200:
                logger.info(f"Successfully sent power off command to {ip}")
                return True
            else:
                logger.error(f"Failed to send power off command. Status code: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error powering off device: {e}")
            return False
    
    def browse_container(self, container_id: str) -> List[Dict]:
        """
        Browse a container on the media server.
        
        Args:
            container_id: ID of the container to browse
            
        Returns:
            List of items in the container, each item being a dictionary with:
            - id: Item ID
            - title: Item title
            - type: 'container' for folders or 'item' for files
            - url: URL for media items (None for containers)
        """
        if not self.current_server:
            logger.error("No media server selected")
            return []
            
        try:
            # Find the ContentDirectory service
            content_directory = next(
                (service for service in self.current_server.services 
                 if 'ContentDirectory' in service.service_type),
                None
            )
            
            if not content_directory:
                logger.error("ContentDirectory service not found")
                return []
            
            # Browse the container
            result = content_directory.Browse(
                ObjectID=container_id,
                BrowseFlag='BrowseDirectChildren',
                Filter='*',
                StartingIndex=0,
                RequestedCount=1000,
                SortCriteria=''
            )
            
            # Parse the DIDL-Lite XML response
            if not result or 'Result' not in result:
                logger.error("Invalid browse result")
                return []
                
            try:
                didl = ElementTree.fromstring(result['Result'])
            except ElementTree.ParseError as e:
                logger.error(f"Error parsing DIDL-Lite: {e}")
                return []
            
            # Extract items from the DIDL-Lite response
            items = []
            for element in didl:
                try:
                    item = {}
                    
                    # Get item type
                    if element.tag.endswith('container'):
                        item['type'] = 'container'
                        item['id'] = element.get('id', '')
                    else:
                        item['type'] = 'item'
                        item['id'] = element.get('id', '')
                        # Get media URL for items
                        res = element.find('.//{*}res')
                        if res is not None:
                            item['url'] = res.text
                    
                    # Get common metadata
                    title = element.find('.//{*}title')
                    if title is not None:
                        item['title'] = title.text
                    else:
                        item['title'] = 'Unknown'
                    
                    items.append(item)
                except Exception as e:
                    logger.error(f"Error processing DIDL-Lite item: {e}")
                    continue
            
            return items
            
        except Exception as e:
            logger.error(f"Error browsing container: {e}", exc_info=True)
            return []
