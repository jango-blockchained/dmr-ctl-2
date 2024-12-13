import unittest
from unittest.mock import Mock, patch, MagicMock
import upnpclient
from dmr_controller.discovery import DeviceDiscovery
from dmr_controller.media_controller import MediaController
import xml.etree.ElementTree as ET

class TestMediaController(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.discovery = Mock(spec=DeviceDiscovery)
        
        # Mock server device
        self.mock_server = Mock(spec=upnpclient.Device)
        self.mock_server.device_type = "urn:schemas-upnp-org:device:MediaServer:1"
        self.mock_server.friendly_name = "Test Media Server"
        self.mock_server.location = "http://192.168.1.100:8200/desc.xml"
        
        # Mock renderer device
        self.mock_renderer = Mock(spec=upnpclient.Device)
        self.mock_renderer.device_type = "urn:schemas-upnp-org:device:MediaRenderer:1"
        self.mock_renderer.friendly_name = "Test Renderer"
        self.mock_renderer.location = "http://192.168.1.101:8200/desc.xml"
        
        # Mock services
        self.mock_av_transport = Mock()
        self.mock_rendering_control = Mock()
        self.mock_content_directory = Mock()
        
        self.mock_renderer.services = [
            self.mock_av_transport,
            self.mock_rendering_control
        ]
        self.mock_av_transport.service_type = "urn:schemas-upnp-org:service:AVTransport:1"
        self.mock_rendering_control.service_type = "urn:schemas-upnp-org:service:RenderingControl:1"
        
        self.mock_server.services = [self.mock_content_directory]
        self.mock_content_directory.service_type = "urn:schemas-upnp-org:service:ContentDirectory:1"
        
        # Create media controller with mocked discovery
        self.media_controller = MediaController()
        self.media_controller.discovery = self.discovery

    def test_set_renderer(self):
        """Test setting a media renderer."""
        # Test valid renderer
        result = self.media_controller.set_renderer(self.mock_renderer)
        self.assertTrue(result)
        self.assertEqual(self.media_controller.current_renderer, self.mock_renderer)
        
        # Test invalid renderer
        invalid_renderer = Mock(spec=upnpclient.Device)
        invalid_renderer.device_type = "urn:schemas-upnp-org:device:InvalidDevice:1"
        result = self.media_controller.set_renderer(invalid_renderer)
        self.assertFalse(result)

    def test_set_server(self):
        """Test setting a media server."""
        # Test valid server
        result = self.media_controller.set_server(self.mock_server)
        self.assertTrue(result)
        self.assertEqual(self.media_controller.current_server, self.mock_server)
        
        # Test invalid server
        invalid_server = Mock(spec=upnpclient.Device)
        invalid_server.device_type = "urn:schemas-upnp-org:device:InvalidDevice:1"
        result = self.media_controller.set_server(invalid_server)
        self.assertFalse(result)

    def test_browse_media_server(self):
        """Test browsing media server content."""
        # Set up mock response for browsing
        mock_items = [
            {
                'id': '1',
                'title': '📁 Music',
                'type': 'container',
                'is_parent': False
            },
            {
                'id': '2',
                'title': 'Test Song.mp3',
                'type': 'audio/mpeg',
                'uri': 'http://192.168.1.100:8200/music/song.mp3',
                'is_parent': False
            }
        ]
        self.discovery.browse_media_server.return_value = mock_items
        
        # Test without setting server first
        result = self.media_controller.browse_media_server("http://192.168.1.100:8200/desc.xml")
        self.assertEqual(result, [])
        
        # Test with server set
        self.media_controller.set_server(self.mock_server)
        result = self.media_controller.browse_media_server("http://192.168.1.100:8200/desc.xml")
        self.assertEqual(result, mock_items)
        self.discovery.browse_media_server.assert_called_with(self.mock_server, "0")
        
        # Test with different object ID
        result = self.media_controller.browse_media_server("http://192.168.1.100:8200/desc.xml", "1")
        self.assertEqual(result, mock_items)
        self.discovery.browse_media_server.assert_called_with(self.mock_server, "1")

    def test_playback_controls(self):
        """Test media playback control functions."""
        # Set up renderer first
        self.media_controller.set_renderer(self.mock_renderer)
        
        # Test play
        self.mock_av_transport.SetAVTransportURI = Mock()
        self.mock_av_transport.Play = Mock()
        
        result = self.media_controller.play("http://test.url/media.mp3")
        self.assertTrue(result)
        self.mock_av_transport.SetAVTransportURI.assert_called_with(
            InstanceID=0,
            CurrentURI="http://test.url/media.mp3",
            CurrentURIMetaData=""
        )
        self.mock_av_transport.Play.assert_called_with(InstanceID=0, Speed="1")
        
        # Test pause
        self.mock_av_transport.Pause = Mock()
        result = self.media_controller.pause()
        self.assertTrue(result)
        self.mock_av_transport.Pause.assert_called_with(InstanceID=0)
        
        # Test stop
        self.mock_av_transport.Stop = Mock()
        result = self.media_controller.stop()
        self.assertTrue(result)
        self.mock_av_transport.Stop.assert_called_with(InstanceID=0)
        
        # Test volume control
        self.mock_rendering_control.SetVolume = Mock()
        result = self.media_controller.set_volume(50)
        self.assertTrue(result)
        self.mock_rendering_control.SetVolume.assert_called_with(
            InstanceID=0,
            Channel='Master',
            DesiredVolume=50
        )

    def test_error_handling(self):
        """Test error handling in media controller."""
        # Test play without renderer
        result = self.media_controller.play("http://test.url/media.mp3")
        self.assertFalse(result)
        
        # Test browse without server
        result = self.media_controller.browse_media_server("http://test.url")
        self.assertEqual(result, [])
        
        # Test with failing service calls
        self.media_controller.set_renderer(self.mock_renderer)
        self.mock_av_transport.Play.side_effect = Exception("Test error")
        result = self.media_controller.play()
        self.assertFalse(result)

class TestDeviceDiscovery(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.discovery = DeviceDiscovery()
        
        # Mock devices
        self.mock_renderer = Mock(spec=upnpclient.Device)
        self.mock_renderer.device_type = "urn:schemas-upnp-org:device:MediaRenderer:1"
        self.mock_renderer.friendly_name = "Test Renderer"
        self.mock_renderer.location = "http://192.168.1.100:1900/desc.xml"
        
        self.mock_server = Mock(spec=upnpclient.Device)
        self.mock_server.device_type = "urn:schemas-upnp-org:device:MediaServer:1"
        self.mock_server.friendly_name = "Test Server"
        self.mock_server.location = "http://192.168.1.100:8200/desc.xml"
        
        # Mock content directory service
        self.mock_content_directory = Mock()
        self.mock_content_directory.service_type = "urn:schemas-upnp-org:service:ContentDirectory:1"
        self.mock_server.services = [self.mock_content_directory]
        
        # Sample DIDL-Lite responses
        self.root_response = {
            "Result": """
            <DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">
                <container id="1" parentID="0" restricted="1">
                    <dc:title>Music</dc:title>
                    <upnp:class>object.container.storageFolder</upnp:class>
                </container>
            </DIDL-Lite>
            """
        }
        
        self.music_folder_response = {
            "Result": """
            <DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">
                <container id="2" parentID="1" restricted="1" childCount="2">
                    <dc:title>Albums</dc:title>
                    <upnp:class>object.container.album</upnp:class>
                </container>
                <item id="3" parentID="1" restricted="1">
                    <dc:title>Song</dc:title>
                    <res protocolInfo="http-get:*:audio/mpeg:*" size="5242880" duration="00:03:45">
                        http://192.168.1.100:8200/music/song.mp3
                    </res>
                    <upnp:class>object.item.audioItem.musicTrack</upnp:class>
                </item>
            </DIDL-Lite>
            """
        }
        
        self.music_folder_metadata = {
            "Result": """
            <DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">
                <container id="1" parentID="0" restricted="1">
                    <dc:title>Music</dc:title>
                    <upnp:class>object.container.storageFolder</upnp:class>
                </container>
            </DIDL-Lite>
            """
        }

    @patch('upnpclient.discover')
    def test_discover_devices(self, mock_discover):
        """Test device discovery."""
        # Setup mock devices
        mock_discover.return_value = [self.mock_renderer, self.mock_server]
        
        # Test discovery
        devices = self.discovery.discover_devices()
        
        self.assertEqual(len(devices), 2)
        self.assertEqual(len(self.discovery.media_renderers), 1)
        self.assertEqual(len(self.discovery.media_servers), 1)
        
        # Verify categorization
        self.assertEqual(self.discovery.media_renderers[0], self.mock_renderer)
        self.assertEqual(self.discovery.media_servers[0], self.mock_server)

    def test_get_device_by_name(self):
        """Test device lookup by name."""
        self.discovery.devices = [self.mock_renderer, self.mock_server]
        
        # Test finding existing device
        device = self.discovery.get_device_by_name("Test Renderer")
        self.assertEqual(device, self.mock_renderer)
        
        # Test case insensitive search
        device = self.discovery.get_device_by_name("test renderer")
        self.assertEqual(device, self.mock_renderer)
        
        # Test non-existent device
        device = self.discovery.get_device_by_name("Nonexistent Device")
        self.assertIsNone(device)

    def test_browse_media_server(self):
        """Test browsing media server content."""
        # Setup browse responses
        self.mock_content_directory.Browse = Mock()
        self.mock_content_directory.Browse.return_value = self.root_response
        
        # Test browsing root
        items = self.discovery.browse_media_server(self.mock_server)
        
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['title'], "📁 Music")
        self.assertEqual(items[0]['type'], 'container')
        
        # Test browsing music folder
        self.mock_content_directory.Browse.return_value = self.music_folder_response
        items = self.discovery.browse_media_server(self.mock_server, "1")
        
        self.assertEqual(len(items), 3)  # Parent + container + item
        self.assertTrue(any(item['title'] == "📁 .." for item in items))
        self.assertTrue(any(item['title'] == "📁 Albums (2)" for item in items))
        self.assertTrue(any("Song" in item['title'] and "[00:03:45]" in item['title'] for item in items))

if __name__ == '__main__':
    unittest.main() 