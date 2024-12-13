import sys
from typing import Optional, List, Dict, Any, Union, cast, Tuple

# pylint: disable=no-name-in-module
from PyQt6.QtWidgets import (  # type: ignore
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QFrame, QLineEdit, QSlider,
    QProgressBar, QGroupBox, QListWidget, QListWidgetItem, QStyle,
    QStatusBar
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot  # type: ignore
from PyQt6.QtGui import QIcon  # type: ignore
# pylint: enable=no-name-in-module

import threading
import time
import queue
import signal
import logging

from .media_controller import MediaController
from .discovery import DeviceDiscovery, discover_media_servers, discover_media_renderers
from .storage import DeviceStorage, DeviceDict

logger = logging.getLogger(__name__)

class ControllerUI(QMainWindow):
    def __init__(self):
        super().__init__()
        logger.info("Initializing DMR Controller UI")
        
        self.setWindowTitle("DMR Controller")
        self.setMinimumSize(800, 600)
        
        # Initialize variables
        self.running: bool = True
        self.discovery: DeviceDiscovery = DeviceDiscovery()
        self.media_controller: MediaController = MediaController()
        self.device_storage: DeviceStorage = DeviceStorage()
        self.current_container_id: str = "0"
        self.browse_history: List[str] = []
        self.path_history: List[str] = ["Root"]
        self.update_queue: queue.Queue = queue.Queue()
        self.discovery_thread: Optional[threading.Thread] = None
        
        # Set up signal handling
        signal.signal(signal.SIGINT, self._handle_interrupt)
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)
        
        self._setup_ui()
        self._load_saved_devices()  # Load devices from storage first
        self._start_background_threads()
        
        logger.info("DMR Controller UI initialized successfully")
    
    def _setup_ui(self):
        # Device Selection Section
        device_group = QGroupBox("Device Selection")
        device_layout = QVBoxLayout()
        
        # Server Selection
        server_layout = QHBoxLayout()
        server_layout.addWidget(QLabel("Media Server:"))
        self.server_combo = QComboBox()
        self.server_combo.currentTextChanged.connect(self.on_server_selected)
        server_layout.addWidget(self.server_combo)
        device_layout.addLayout(server_layout)
        
        # Add Media Browser Section
        browser_group = QGroupBox("Media Browser")
        browser_layout = QVBoxLayout()
        
        # Path navigation
        nav_layout = QHBoxLayout()
        back_btn = QPushButton("⬅ Back")
        back_btn.clicked.connect(self._browse_back)
        nav_layout.addWidget(back_btn)
        
        self.path_label = QLabel("Root")
        nav_layout.addWidget(self.path_label)
        browser_layout.addLayout(nav_layout)
        
        # Content list
        self.content_list = QListWidget()
        self.content_list.itemDoubleClicked.connect(self._on_content_item_clicked)
        browser_layout.addWidget(self.content_list)
        
        browser_group.setLayout(browser_layout)
        device_layout.addWidget(browser_group)
        
        # Renderer Selection
        renderer_layout = QHBoxLayout()
        renderer_layout.addWidget(QLabel("Media Renderer:"))
        self.renderer_combo = QComboBox()
        self.renderer_combo.currentTextChanged.connect(self._on_renderer_selected)
        renderer_layout.addWidget(self.renderer_combo)
        device_layout.addLayout(renderer_layout)
        
        # Control buttons
        control_layout = QHBoxLayout()
        power_on_btn = QPushButton("⚡ On")
        power_on_btn.clicked.connect(self._power_on_renderer)
        power_off_btn = QPushButton("⭘ Off")
        power_off_btn.clicked.connect(self._power_off_renderer)
        refresh_btn = QPushButton("⟳ Discover Devices")
        refresh_btn.clicked.connect(self._start_discovery)
        
        control_layout.addWidget(power_on_btn)
        control_layout.addWidget(power_off_btn)
        control_layout.addWidget(refresh_btn)
        device_layout.addLayout(control_layout)
        
        # Input source
        source_layout = QHBoxLayout()
        source_layout.addWidget(QLabel("Input:"))
        self.source_combo = QComboBox()
        self.source_combo.currentTextChanged.connect(self._on_input_source_changed)
        source_layout.addWidget(self.source_combo)
        device_layout.addLayout(source_layout)
        
        device_group.setLayout(device_layout)
        self.main_layout.addWidget(device_group)
        
        # Now Playing Section
        playback_group = QGroupBox("Now Playing")
        playback_layout = QVBoxLayout()
        
        self.title_label = QLabel("No media playing")
        self.artist_label = QLabel("")
        self.album_label = QLabel("")
        self.position_label = QLabel("00:00:00 / 00:00:00")
        self.state_label = QLabel("STOPPED")
        
        playback_layout.addWidget(self.title_label)
        playback_layout.addWidget(self.artist_label)
        playback_layout.addWidget(self.album_label)
        
        position_layout = QHBoxLayout()
        position_layout.addWidget(self.position_label)
        position_layout.addWidget(self.state_label)
        playback_layout.addLayout(position_layout)
        
        playback_group.setLayout(playback_layout)
        self.main_layout.addWidget(playback_group)
        
        # Media Controls Section
        controls_group = QGroupBox("Media Controls")
        controls_layout = QVBoxLayout()
        
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("Media URL:"))
        self.url_entry = QLineEdit()
        url_layout.addWidget(self.url_entry)
        controls_layout.addLayout(url_layout)
        
        # Add time seek controls
        seek_layout = QHBoxLayout()
        seek_layout.addWidget(QLabel("Seek to (HH:MM:SS):"))
        self.time_entry = QLineEdit()
        self.time_entry.setPlaceholderText("00:00:00")
        seek_layout.addWidget(self.time_entry)
        seek_btn = QPushButton("⏩ Seek")
        seek_btn.clicked.connect(self._seek_to_time)
        seek_layout.addWidget(seek_btn)
        controls_layout.addLayout(seek_layout)
        
        buttons_layout = QHBoxLayout()
        play_btn = QPushButton("▶ Play")
        play_btn.clicked.connect(self._play)
        pause_btn = QPushButton("⏸ Pause")
        pause_btn.clicked.connect(self._pause)
        stop_btn = QPushButton("⏹ Stop")
        stop_btn.clicked.connect(self._stop)
        
        buttons_layout.addWidget(play_btn)
        buttons_layout.addWidget(pause_btn)
        buttons_layout.addWidget(stop_btn)
        controls_layout.addLayout(buttons_layout)
        
        volume_layout = QHBoxLayout()
        volume_layout.addWidget(QLabel("Volume:"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.volume_slider.valueChanged.connect(self._on_volume_change)
        volume_layout.addWidget(self.volume_slider)
        controls_layout.addLayout(volume_layout)
        
        controls_group.setLayout(controls_layout)
        self.main_layout.addWidget(controls_group)
        
        # Local Playback Section
        local_group = QGroupBox("Local Playback")
        local_layout = QVBoxLayout()
        
        browse_btn = QPushButton("Browse Files")
        browse_btn.clicked.connect(self.media_controller.browse_local_file)
        local_layout.addWidget(browse_btn)
        
        soundcloud_layout = QHBoxLayout()
        soundcloud_layout.addWidget(QLabel("Soundcloud URL:"))
        self.soundcloud_entry = QLineEdit()
        self.soundcloud_entry.setPlaceholderText("Enter Soundcloud URL...")
        soundcloud_layout.addWidget(self.soundcloud_entry)
        self.soundcloud_entry.textChanged.connect(lambda: self.soundcloud_entry.setText(self.soundcloud_entry.text().rstrip()))
        soundcloud_btn = QPushButton("Play Soundcloud")
        soundcloud_btn.clicked.connect(self.play_soundcloud)
        soundcloud_layout.addWidget(soundcloud_btn)
        local_layout.addLayout(soundcloud_layout)

        local_group.setLayout(local_layout)
        self.main_layout.addWidget(local_group)
        
        # Initialize status bar
        self.status_bar = self.statusBar()
        if self.status_bar is None:
            logger.error("Failed to create status bar")
            raise RuntimeError("Failed to create status bar")
            
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(150)
        self.progress_bar.setMaximumHeight(15)
        self.progress_bar.hide()  # Hide initially
        self.status_bar.addPermanentWidget(self.progress_bar)
        self.status_bar.showMessage("Ready")
        
        # Disable input source combo box initially
        self.source_combo.setEnabled(False)
        
        # Start background thread to get current input source
        threading.Thread(target=self._init_input_source, daemon=True).start()
    
    def _init_input_source(self):
        """Initialize input source in background."""
        try:
            self.update_queue.put(("update_status", "Initializing input sources..."))
            self.update_queue.put(("show_progress", None))
            
            # Get current input source
            if self.media_controller.current_renderer:
                current_input = self.media_controller.get_current_input()
                sources = self.media_controller.get_input_sources()
                
                if sources:
                    self.update_queue.put(("update_input_sources", {
                        'sources': sources,
                        'current': current_input
                    }))
                    self.update_queue.put(("update_status", "Input sources initialized"))
                else:
                    self.update_queue.put(("update_status", "No input sources available"))
            
            self.update_queue.put(("hide_progress", None))
        except Exception as e:
            logger.error(f"Error initializing input sources: {e}")
            self.update_queue.put(("update_status", f"Error initializing input sources: {e}"))
            self.update_queue.put(("hide_progress", None))
    
    def _start_background_threads(self):
        threading.Thread(target=self._media_info_worker, daemon=True).start()
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._process_updates)
        self.update_timer.start(100)
    
    def _media_info_worker(self):
        while self.running:
            try:
                if self.media_controller.current_renderer:
                    info = self.media_controller.get_media_info()
                    if info:
                        self.update_queue.put(("update_media_info", info))
                    else:
                        self.update_queue.put(("reset_media_info", None))
            except Exception as e:
                logger.debug(f"Error in media info worker: {e}")
                self.update_queue.put(("reset_media_info", None))
            time.sleep(1)
    
    def _process_updates(self):
        """Process UI updates from the queue."""
        if not self.running:
            return
            
        try:
            while not self.update_queue.empty():
                action, data = self.update_queue.get_nowait()
                
                if action == "discovery_complete":
                    servers, renderers = data
                    self._update_device_lists(servers, renderers)
                    self._update_status_safe("Device discovery completed")
                    self.progress_bar.hide()
                    
                elif action == "discovery_error":
                    self._update_status_safe(f"Discovery error: {data}")
                    self.progress_bar.hide()
                    
                elif action == "update_media_info":
                    self.title_label.setText(data['title'])
                    self.artist_label.setText(data['artist'])
                    self.album_label.setText(data['album'])
                    self.position_label.setText(f"{data['position']} / {data['duration']}")
                    self.state_label.setText(data['state'])
                    
                    if 'volume' in data:
                        try:
                            volume = int(data['volume'])
                            if 0 <= volume <= 100:
                                self.volume_slider.setValue(volume)
                        except (ValueError, TypeError):
                            pass
                            
                elif action == "reset_media_info":
                    self.title_label.setText("No media playing")
                    self.artist_label.setText("")
                    self.album_label.setText("")
                    self.position_label.setText("00:00:00 / 00:00:00")
                    self.state_label.setText("STOPPED")
                    
                elif action == "update_status":
                    self.status_bar.showMessage(data)
                    
                elif action == "show_progress":
                    self.progress_bar.setRange(0, 0)  # Indeterminate progress
                    self.progress_bar.show()
                    
                elif action == "hide_progress":
                    self.progress_bar.hide()
                    
                elif action == "update_input_sources":
                    self.source_combo.clear()
                    for source in data['sources']:
                        self.source_combo.addItem(source)
                    if data['current']:
                        self.source_combo.setCurrentText(data['current'])
                    self.source_combo.setEnabled(True)
                    
        except queue.Empty:
            pass
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, shutting down...")
            self.running = False
            self.close()
        except Exception as e:
            logger.error(f"Error processing UI updates: {e}")
    
    def closeEvent(self, event):
        self.running = False
        super().closeEvent(event)
    
    def _play(self):
        try:
            url = self.url_entry.text()
            if url and self.media_controller.play(url):
                self._update_status_safe("Playing")
            else:
                self._update_status_safe("Failed to play media")
        except Exception as e:
            error_msg = f"Error playing media: {e}"
            logger.error(error_msg, exc_info=True)
            self._update_status_safe(error_msg)
    
    def _pause(self):
        try:
            if self.media_controller.pause():
                self._update_status_safe("Paused")
            else:
                self._update_status_safe("Failed to pause media")
        except Exception as e:
            error_msg = f"Error pausing media: {e}"
            logger.error(error_msg, exc_info=True)
            self._update_status_safe(error_msg)
    
    def _stop(self):
        try:
            if self.media_controller.stop():
                self._update_status_safe("Stopped")
            else:
                self._update_status_safe("Failed to stop media")
        except Exception as e:
            error_msg = f"Error stopping media: {e}"
            logger.error(error_msg, exc_info=True)
            self._update_status_safe(error_msg)
    
    def _seek_to_time(self):
        """Handle seeking to a specific time."""
        try:
            time_str = self.time_entry.text()
            if not time_str:
                self._update_status_safe("Please enter a time in HH:MM:SS format")
                return
            
            # Parse time string
            try:
                h, m, s = map(int, time_str.split(':'))
                total_seconds = h * 3600 + m * 60 + s
            except ValueError:
                self._update_status_safe("Invalid time format. Please use HH:MM:SS")
                return
            
            # Get current transport info to check if we're playing
            transport_info = self.media_controller.get_transport_info()
            if not transport_info:
                self._update_status_safe("No media is currently playing")
                return
            
            # Get current position info to check media duration
            position_info = self.media_controller.get_position_info()
            if not position_info:
                self._update_status_safe("Could not get media duration")
                return
            
            # Check if the requested time is within the media duration
            try:
                duration = position_info.get('TrackDuration', '00:00:00')
                h, m, s = map(int, duration.split(':'))
                duration_seconds = h * 3600 + m * 60 + s
                
                if total_seconds > duration_seconds:
                    self._update_status_safe(f"Requested time exceeds media duration ({duration})")
                    return
            except (ValueError, AttributeError):
                logger.warning("Could not parse media duration")
            
            # Seek to the specified time
            if self.media_controller._av_transport:
                try:
                    self.media_controller._av_transport.Seek(
                        InstanceID=0,
                        Unit='REL_TIME',
                        Target=f"{h:02d}:{m:02d}:{s:02d}"
                    )
                    self._update_status_safe(f"Seeked to {time_str}")
                except Exception as e:
                    error_msg = f"Error seeking: {e}"
                    logger.error(error_msg, exc_info=True)
                    self._update_status_safe(error_msg)
            else:
                self._update_status_safe("No transport service available")
        except Exception as e:
            error_msg = f"Error seeking to time: {e}"
            logger.error(error_msg, exc_info=True)
            self._update_status_safe(error_msg)
    
    def _on_volume_change(self, value):
        try:
            if self.media_controller.set_volume(value):
                self._update_status_safe(f"Volume: {value}%")
            else:
                self._update_status_safe("Failed to set volume")
        except Exception as e:
            error_msg = f"Error setting volume: {e}"
            logger.error(error_msg, exc_info=True)
            self._update_status_safe(error_msg)
    
    def _get_renderer_ip(self, renderer_name: str) -> Optional[str]:
        """Get renderer IP from stored devices or current selection."""
        try:
            # First try to get from stored devices
            _, renderers = self.device_storage.load_devices()
            for renderer in renderers:
                if renderer['friendly_name'] == renderer_name:
                    return renderer['location'].split('/')[2].split(':')[0]
            
            # If not found in storage, fall back to discovery
            logger.info("Renderer not found in storage, falling back to discovery")
            renderers = discover_media_renderers()
            for renderer in renderers:
                if isinstance(renderer, dict):
                    if renderer['friendly_name'] == renderer_name:
                        return renderer['location'].split('/')[2].split(':')[0]
                else:
                    if renderer.friendly_name == renderer_name:
                        return renderer.location.split('/')[2].split(':')[0]
            
            return None
        except Exception as e:
            logger.error(f"Error getting renderer IP: {e}", exc_info=True)
            return None

    def _power_on_renderer(self):
        """Power on the selected renderer using stored device information."""
        try:
            selected_renderer = self.renderer_combo.currentText()
            if not selected_renderer:
                self._update_status_safe("No renderer selected")
                return
            
            ip = self._get_renderer_ip(selected_renderer)
            if ip:
                self.media_controller.power_on(ip)
                self._update_status_safe(f"Power on command sent to {ip}")
                logger.info(f"Power on command sent successfully to {ip}")
            else:
                self._update_status_safe("Failed to find renderer IP")
        except Exception as e:
            error_msg = f"Error powering on renderer: {e}"
            logger.error(error_msg, exc_info=True)
            self._update_status_safe(error_msg)
    
    def _power_off_renderer(self):
        """Power off the selected renderer using stored device information."""
        try:
            selected_renderer = self.renderer_combo.currentText()
            if not selected_renderer:
                self._update_status_safe("No renderer selected")
                return
            
            ip = self._get_renderer_ip(selected_renderer)
            if ip:
                self.media_controller.power_off(ip)
                self._update_status_safe(f"Power off command sent to {ip}")
                logger.info(f"Power off command sent successfully to {ip}")
            else:
                self._update_status_safe("Failed to find renderer IP")
        except Exception as e:
            error_msg = f"Error powering off renderer: {e}"
            logger.error(error_msg, exc_info=True)
            self._update_status_safe(error_msg)
    
    def _on_input_source_changed(self, source):
        if source:
            if self.media_controller.set_input_source(source):
                self._update_status_safe(f"Input source changed to {source}")
            else:
                self._update_status_safe(f"Failed to change input source to {source}")
                current_input = self.media_controller.get_current_input()
                if current_input:
                    self.source_combo.setCurrentText(current_input)
    
    def _update_status_safe(self, message: str) -> None:
        """Safely update status bar message."""
        if self.status_bar is not None:
            self.status_bar.showMessage(message)
        else:
            logger.warning(f"Status bar not available to show message: {message}")
    
    def play_soundcloud(self):
        url = self.soundcloud_entry.text()
        if url and url != "Enter Soundcloud URL...":
            self.media_controller.play_soundcloud(url)
    
    def _start_discovery(self):
        """Start device discovery in background thread."""
        if self.discovery_thread and self.discovery_thread.is_alive():
            self._update_status_safe("Discovery already in progress...")
            return
            
        self._update_status_safe("Starting device discovery...")
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        self.progress_bar.show()
        self.discovery_thread = threading.Thread(
            target=self._run_discovery,
            daemon=True
        )
        self.discovery_thread.start()

    def _run_discovery(self):
        """Run device discovery and save results."""
        try:
            logger.info("Starting device discovery...")
            
            # Run discovery
            servers = discover_media_servers()
            renderers = discover_media_renderers()
            
            # Log discovered devices
            logger.info(f"Found {len(servers)} media servers and {len(renderers)} renderers")
            
            for server in servers:
                if isinstance(server, dict):
                    logger.info(f"Server (dict): {server}")
                else:
                    try:
                        logger.info(f"Server (obj): name='{server.friendly_name}', type='{server.device_type}', location='{server.location}'")
                        logger.info(f"  Services: {[s.service_type for s in server.services]}")
                    except Exception as e:
                        logger.error(f"Error logging server info: {e}", exc_info=True)
            
            for renderer in renderers:
                if isinstance(renderer, dict):
                    logger.info(f"Renderer (dict): {renderer}")
                else:
                    try:
                        logger.info(f"Renderer (obj): name='{renderer.friendly_name}', type='{renderer.device_type}', location='{renderer.location}'")
                        logger.info(f"  Services: {[s.service_type for s in renderer.services]}")
                    except Exception as e:
                        logger.error(f"Error logging renderer info: {e}", exc_info=True)
            
            # Convert devices to dictionaries for storage
            server_dicts: List[DeviceDict] = []
            for server in servers:
                try:
                    if isinstance(server, dict):
                        # Ensure the dictionary has all required fields
                        device_dict = {
                            'friendly_name': str(server.get('friendly_name', '')),
                            'location': str(server.get('location', '')),
                            'device_type': str(server.get('device_type', 'urn:schemas-upnp-org:device:MediaServer:1'))
                        }
                    else:
                        # Convert object attributes to dictionary
                        device_dict = {
                            'friendly_name': str(getattr(server, 'friendly_name', '')),
                            'location': str(getattr(server, 'location', '')),
                            'device_type': str(getattr(server, 'device_type', 'urn:schemas-upnp-org:device:MediaServer:1'))
                        }
                    
                    # Log the conversion
                    logger.debug(f"Converting server to dict: {device_dict}")
                    
                    # Only add if we have valid data
                    if device_dict['friendly_name'] and device_dict['location']:
                        # Cast to DeviceDict before appending
                        typed_dict = DeviceDict(
                            friendly_name=str(device_dict['friendly_name']),
                            location=str(device_dict['location']),
                            device_type=str(device_dict.get('device_type', ''))
                        )
                        server_dicts.append(typed_dict)
                        logger.info(f"Added server: {typed_dict['friendly_name']}")
                    else:
                        logger.warning(f"Skipping invalid server: {device_dict}")
                except Exception as e:
                    logger.error(f"Error converting server to dict: {e}", exc_info=True)
            
            renderer_dicts: List[DeviceDict] = []
            for renderer in renderers:
                try:
                    if isinstance(renderer, dict):
                        # Ensure the dictionary has all required fields
                        device_dict = {
                            'friendly_name': str(renderer.get('friendly_name', '')),
                            'location': str(renderer.get('location', '')),
                            'device_type': str(renderer.get('device_type', 'urn:schemas-upnp-org:device:MediaRenderer:1'))
                        }
                    else:
                        # Convert object attributes to dictionary
                        device_dict = {
                            'friendly_name': str(getattr(renderer, 'friendly_name', '')),
                            'location': str(getattr(renderer, 'location', '')),
                            'device_type': str(getattr(renderer, 'device_type', 'urn:schemas-upnp-org:device:MediaRenderer:1'))
                        }
                    
                    # Log the conversion
                    logger.debug(f"Converting renderer to dict: {device_dict}")
                    
                    # Only add if we have valid data
                    if device_dict['friendly_name'] and device_dict['location']:
                        renderer_dicts.append(device_dict)
                        logger.info(f"Added renderer: {device_dict['friendly_name']}")
                    else:
                        logger.warning(f"Skipping invalid renderer: {device_dict}")
                except Exception as e:
                    logger.error(f"Error converting renderer to dict: {e}", exc_info=True)
            
            # Save to storage only if we have valid devices
            if server_dicts or renderer_dicts:
                if self.device_storage.save_devices(server_dicts, renderer_dicts):
                    self.update_queue.put(("discovery_complete", (servers, renderers)))
                    logger.info(f"Successfully saved {len(server_dicts)} servers and {len(renderer_dicts)} renderers")
                else:
                    self.update_queue.put(("discovery_error", "Failed to save discovered devices"))
            else:
                logger.warning("No valid devices found during discovery")
                self.update_queue.put(("discovery_error", "No valid devices found"))
                
        except Exception as e:
            logger.error(f"Error during discovery: {e}", exc_info=True)
            self.update_queue.put(("discovery_error", str(e)))

    def _load_saved_devices(self) -> Tuple[List[DeviceDict], List[DeviceDict]]:
        """Load devices from storage on startup."""
        try:
            servers, renderers = self.device_storage.load_devices()
            
            # Update UI with loaded devices
            self._update_device_lists(servers, renderers)
            
            if not servers and not renderers:
                self._update_status_safe("No saved devices found. Please run discovery.")
            else:
                self._update_status_safe(f"Loaded {len(servers)} servers and {len(renderers)} renderers from storage")
                logger.info(f"Successfully loaded {len(servers)} servers and {len(renderers)} renderers from storage")
            return servers, renderers
        except Exception as e:
            error_msg = f"Error loading saved devices: {e}"
            logger.error(error_msg, exc_info=True)
            self._update_status_safe(error_msg)
            # Fallback to empty lists
            return [], []

    def _update_device_lists(self, servers: List[DeviceDict], renderers: List[DeviceDict]) -> None:
        """Update UI device lists with discovered or loaded devices."""
        # Update server combo box
        self.server_combo.clear()
        for server in servers:
            try:
                name = server.get('friendly_name')
                if not name:
                    logger.warning(f"Server missing friendly_name: {server}")
                    continue
                self.server_combo.addItem(name)
            except Exception as e:
                logger.error(f"Error adding server to list: {e}", exc_info=True)

        # Update renderer combo box
        self.renderer_combo.clear()
        for renderer in renderers:
            try:
                name = renderer.get('friendly_name')
                if not name:
                    logger.warning(f"Renderer missing friendly_name: {renderer}")
                    continue
                self.renderer_combo.addItem(name)
            except Exception as e:
                logger.error(f"Error adding renderer to list: {e}", exc_info=True)

    def on_server_selected(self):
        """Handle server selection."""
        server_name = self.server_combo.currentText()
        if server_name:
            try:
                servers = discover_media_servers()
                for server in servers:
                    if isinstance(server, dict):
                        if server['friendly_name'] == server_name:
                            if self.media_controller.set_server(server):
                                # Reset browse history
                                self.browse_history = ["0"]
                                self.path_history = ["Root"]
                                self.current_container_id = "0"
                                self.path_label.setText("Root")
                                
                                # Browse root container
                                self._browse_container("0")
                                self._update_status_safe(f"Selected media server: {server_name}")
                            return
                    else:
                        if server.friendly_name == server_name:
                            if self.media_controller.set_server(server):
                                # Reset browse history
                                self.browse_history = ["0"]
                                self.path_history = ["Root"]
                                self.current_container_id = "0"
                                self.path_label.setText("Root")
                                
                                # Browse root container
                                self._browse_container("0")
                                self._update_status_safe(f"Selected media server: {server_name}")
                            return
                
                self._update_status_safe("Failed to find selected media server")
            except Exception as e:
                error_msg = f"Error selecting media server: {e}"
                logger.error(error_msg, exc_info=True)
                self._update_status_safe(error_msg)
    
    def _on_renderer_selected(self, renderer_name):
        """Handle renderer selection."""
        if renderer_name:
            try:
                # Disable input source combo box while loading
                self.source_combo.setEnabled(False)
                self.source_combo.clear()
                
                renderers = discover_media_renderers()
                for renderer in renderers:
                    if isinstance(renderer, dict):
                        if renderer['friendly_name'] == renderer_name:
                            # Create a device-like object from the dictionary
                            class DeviceWrapper:
                                def __init__(self, device_dict):
                                    self.device_type = 'urn:schemas-upnp-org:device:MediaRenderer:1'
                                    self.friendly_name = device_dict['friendly_name']
                                    self.location = device_dict['location']
                                    
                                    # Create AVTransport and RenderingControl services
                                    class ServiceWrapper:
                                        def __init__(self, service_type):
                                            self.service_type = service_type
                                    
                                    self.services = [
                                        ServiceWrapper('urn:schemas-upnp-org:service:AVTransport:1'),
                                        ServiceWrapper('urn:schemas-upnp-org:service:RenderingControl:1')
                                    ]
                            
                            device = DeviceWrapper(renderer)
                            if self.media_controller.set_renderer(device):
                                # Start background thread to get input sources
                                threading.Thread(target=self._init_input_source, daemon=True).start()
                                self._update_status_safe(f"Selected media renderer: {renderer_name}")
                            return
                    else:
                        if renderer.friendly_name == renderer_name:
                            if self.media_controller.set_renderer(renderer):
                                # Start background thread to get input sources
                                threading.Thread(target=self._init_input_source, daemon=True).start()
                                self._update_status_safe(f"Selected media renderer: {renderer_name}")
                            return
                
                self._update_status_safe("Failed to find selected media renderer")
            except Exception as e:
                error_msg = f"Error selecting media renderer: {e}"
                logger.error(error_msg, exc_info=True)
                self._update_status_safe(error_msg)
    
    def _handle_interrupt(self, signum, frame):
        """Handle interrupt signal (Ctrl+C)."""
        logger.info("Received interrupt signal, shutting down...")
        self.running = False
        self.close()
    
    def _browse_back(self):
        """Navigate back in the media browser."""
        if len(self.browse_history) > 1:
            # Remove current location
            self.browse_history.pop()
            self.path_history.pop()
            
            # Get previous location
            container_id = self.browse_history[-1]
            self.current_container_id = container_id
            
            # Update path label
            self.path_label.setText(" / ".join(self.path_history))
            
            # Browse to previous location
            self._browse_container(container_id)

    def _on_content_item_clicked(self, item):
        """Handle double-click on content items."""
        try:
            data = item.data(Qt.ItemDataRole.UserRole)
            if not data:
                return
                
            if data.get("type") == "container":
                # It's a folder, browse into it
                container_id = data.get("id")
                if container_id:
                    self.browse_history.append(container_id)
                    self.path_history.append(item.text())
                    self.current_container_id = container_id
                    self.path_label.setText(" / ".join(self.path_history))
                    self._browse_container(container_id)
            else:
                # It's a playable item
                url = data.get("url")
                if url:
                    self.url_entry.setText(url)
                    self._play()
        except Exception as e:
            logger.error(f"Error handling content item click: {e}", exc_info=True)

    def _browse_container(self, container_id: str):
        """Browse a container's contents."""
        try:
            if not self.media_controller.current_server:
                self._update_status_safe("No media server selected")
                return
                
            # Clear current list
            self.content_list.clear()
            
            # Get container contents
            result = self.media_controller.browse_container(container_id)
            if not result:
                self._update_status_safe("Failed to browse container")
                return
                
            # Parse and display results
            for item in result:
                list_item = QListWidgetItem()
                
                # Set icon based on type
                if item.get("type") == "container":
                    list_item.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
                else:
                    list_item.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
                
                # Set item text and data
                list_item.setText(item.get("title", "Unknown"))
                list_item.setData(Qt.ItemDataRole.UserRole, item)
                
                self.content_list.addItem(list_item)
                
            self._update_status_safe(f"Found {self.content_list.count()} items")
        except Exception as e:
            logger.error(f"Error browsing container: {e}", exc_info=True)
            self._update_status_safe("Error browsing media")
    
    def run(self):
        """Show the window and start the application event loop."""
        self.show()  # Shows the window

    def _convert_device_to_dict(self, device: Any) -> DeviceDict:
        """Convert a device object to a DeviceDict."""
        try:
            # Get device info
            if isinstance(device, dict):
                friendly_name = device.get('friendly_name', '')
                location = device.get('location', '')
                device_type = device.get('device_type', '')
            else:
                friendly_name = getattr(device, 'friendly_name', '')
                location = getattr(device, 'location', '')
                device_type = getattr(device, 'device_type', '')
                
            # Create and validate device dict
            device_dict: DeviceDict = {
                'friendly_name': str(friendly_name),
                'location': str(location),
                'device_type': str(device_type)
            }
            
            return device_dict
        except Exception as e:
            logger.error(f"Error converting device to dict: {e}", exc_info=True)
            # Return empty but valid DeviceDict
            return DeviceDict(friendly_name='', location='', device_type='')

    def _discover_devices(self):
        """Run device discovery in a separate thread."""
        try:
            # Clear existing devices
            server_dicts: List[DeviceDict] = []
            renderer_dicts: List[DeviceDict] = []
            
            # Discover devices
            servers = self.media_controller.discovery.discover_media_servers()
            renderers = self.media_controller.discovery.discover_media_renderers()
            
            # Convert servers to dicts
            for server in servers:
                try:
                    device_dict = self._convert_device_to_dict(server)
                    
                    # Log the conversion
                    logger.debug(f"Converting server to dict: {device_dict}")
                    
                    # Only add if we have valid data
                    if device_dict['friendly_name'] and device_dict['location']:
                        # Cast to DeviceDict before appending
                        typed_dict = DeviceDict(
                            friendly_name=str(device_dict['friendly_name']),
                            location=str(device_dict['location']),
                            device_type=str(device_dict.get('device_type', ''))
                        )
                        server_dicts.append(typed_dict)
                        logger.info(f"Added server: {typed_dict['friendly_name']}")
                    else:
                        logger.warning(f"Skipping invalid server: {device_dict}")
                except Exception as e:
                    logger.error(f"Error converting server to dict: {e}", exc_info=True)