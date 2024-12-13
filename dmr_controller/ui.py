import sys
from typing import Optional, List, Dict, Any, Union, cast, Tuple

# pylint: disable=no-name-in-module
from PyQt6.QtWidgets import (  # type: ignore
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QFrame, QLineEdit, QSlider,
    QProgressBar, QGroupBox, QListWidget, QListWidgetItem, QStyle,
    QStatusBar, QGridLayout
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
        
        # Renderer Selection with Discovery
        renderer_layout = QHBoxLayout()
        renderer_layout.addWidget(QLabel("Media Renderer:"))
        self.renderer_combo = QComboBox()
        self.renderer_combo.setToolTip("Select a media renderer device")
        self.renderer_combo.currentTextChanged.connect(self._on_renderer_selected)
        renderer_layout.addWidget(self.renderer_combo)
        refresh_btn = QPushButton("⟳ Discover")
        refresh_btn.setToolTip("Search for available media renderers")
        refresh_btn.clicked.connect(self._start_discovery)
        renderer_layout.addWidget(refresh_btn)
        device_layout.addLayout(renderer_layout)
        
        # Receiver Controls Section
        receiver_group = QGroupBox("Receiver Controls")
        receiver_layout = QVBoxLayout()
        
        # IP Address input
        ip_layout = QHBoxLayout()
        ip_layout.addWidget(QLabel("IP Address:"))
        self.receiver_ip_input = QLineEdit()
        self.receiver_ip_input.setPlaceholderText("Enter receiver IP...")
        self.receiver_ip_input.setToolTip("Enter the IP address of your receiver")
        connect_btn = QPushButton("Connect")
        connect_btn.setToolTip("Connect to the receiver")
        connect_btn.clicked.connect(self._connect_receiver)
        ip_layout.addWidget(self.receiver_ip_input)
        ip_layout.addWidget(connect_btn)
        receiver_layout.addLayout(ip_layout)
        
        # Receiver Controls Grid
        receiver_controls = QGridLayout()
        
        # Power controls
        power_label = QLabel("Power")
        receiver_controls.addWidget(power_label, 0, 0)
        power_btns = QHBoxLayout()
        receiver_on_btn = QPushButton("On")
        receiver_on_btn.setToolTip("Turn receiver on")
        receiver_on_btn.clicked.connect(lambda: self._set_receiver_power(True))
        receiver_off_btn = QPushButton("Off")
        receiver_off_btn.setToolTip("Turn receiver off")
        receiver_off_btn.clicked.connect(lambda: self._set_receiver_power(False))
        power_btns.addWidget(receiver_on_btn)
        power_btns.addWidget(receiver_off_btn)
        power_widget = QWidget()
        power_widget.setLayout(power_btns)
        receiver_controls.addWidget(power_widget, 0, 1)
        
        # Volume control
        volume_label = QLabel("Volume")
        receiver_controls.addWidget(volume_label, 1, 0)
        self.receiver_volume = QSlider(Qt.Orientation.Horizontal)
        self.receiver_volume.setToolTip("Adjust volume")
        self.receiver_volume.setRange(0, 100)
        self.receiver_volume.setValue(50)
        self.receiver_volume.valueChanged.connect(self._on_receiver_volume_change)
        receiver_controls.addWidget(self.receiver_volume, 1, 1)
        
        # Input selection
        input_label = QLabel("Input")
        receiver_controls.addWidget(input_label, 2, 0)
        self.receiver_input = QComboBox()
        self.receiver_input.setToolTip("Select input source")
        self.receiver_input.currentTextChanged.connect(self._on_receiver_input_change)
        receiver_controls.addWidget(self.receiver_input, 2, 1)
        
        # Mute control
        mute_label = QLabel("Mute")
        receiver_controls.addWidget(mute_label, 3, 0)
        self.receiver_mute = QPushButton("Mute")
        self.receiver_mute.setToolTip("Toggle mute")
        self.receiver_mute.setCheckable(True)
        self.receiver_mute.clicked.connect(self._on_receiver_mute_toggle)
        receiver_controls.addWidget(self.receiver_mute, 3, 1)
        
        receiver_layout.addLayout(receiver_controls)
        receiver_group.setLayout(receiver_layout)
        device_layout.addWidget(receiver_group)
        
        # Media Source Section
        source_group = QGroupBox("Media Source")
        source_layout = QVBoxLayout()
        
        # Source Selection Grid
        source_grid = QGridLayout()
        
        # Server Selection
        source_grid.addWidget(QLabel("Media Server:"), 0, 0)
        self.server_combo = QComboBox()
        self.server_combo.setToolTip("Select a media server")
        self.server_combo.currentTextChanged.connect(self.on_server_selected)
        source_grid.addWidget(self.server_combo, 0, 1)
        
        # Content Source Selection
        source_grid.addWidget(QLabel("Content Source:"), 1, 0)
        self.content_source_combo = QComboBox()
        self.content_source_combo.setToolTip("Select content source type")
        self.content_source_combo.addItems(["Media Server", "Local File", "Soundcloud/Youtube"])
        self.content_source_combo.currentTextChanged.connect(self._on_content_source_changed)
        source_grid.addWidget(self.content_source_combo, 1, 1)
        
        source_layout.addLayout(source_grid)
        
        # Content Browser
        browser_layout = QVBoxLayout()
        
        # Create input widgets for different sources
        self.file_input = QPushButton("Browse Files")
        self.file_input.setToolTip("Browse for local media files")
        self.file_input.clicked.connect(self.media_controller.browse_local_file)
        self.file_input.hide()
        
        self.url_input_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter Soundcloud/Youtube URL...")
        self.url_input.setToolTip("Enter URL from Soundcloud or Youtube")
        self.url_play_btn = QPushButton("Play")
        self.url_play_btn.setToolTip("Play URL")
        self.url_play_btn.clicked.connect(self.play_url)
        self.url_input_layout.addWidget(self.url_input)
        self.url_input_layout.addWidget(self.url_play_btn)
        self.url_widget = QWidget()
        self.url_widget.setLayout(self.url_input_layout)
        self.url_widget.hide()
        
        # Add inputs to browser layout
        browser_layout.addWidget(self.file_input)
        browser_layout.addWidget(self.url_widget)
        
        # Path navigation
        nav_layout = QHBoxLayout()
        back_btn = QPushButton("⬅ Back")
        back_btn.setToolTip("Go back to previous folder")
        back_btn.clicked.connect(self._browse_back)
        nav_layout.addWidget(back_btn)
        
        self.path_label = QLabel("Root")
        nav_layout.addWidget(self.path_label)
        browser_layout.addLayout(nav_layout)
        
        # Content list
        self.content_list = QListWidget()
        self.content_list.setToolTip("Double-click to play or browse")
        self.content_list.setMinimumHeight(200)  # Make list more visible
        self.content_list.itemDoubleClicked.connect(self._on_content_item_clicked)
        browser_layout.addWidget(self.content_list)
        
        source_layout.addLayout(browser_layout)
        source_group.setLayout(source_layout)
        device_layout.addWidget(source_group)
        
        # Device group layout
        device_group.setLayout(device_layout)
        self.main_layout.addWidget(device_group)
        
        # Now Playing Section
        playback_group = QGroupBox("Now Playing")
        playback_layout = QVBoxLayout()
        
        self.title_label = QLabel("No media playing")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.artist_label = QLabel("")
        self.artist_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.album_label = QLabel("")
        self.album_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.position_label = QLabel("00:00:00 / 00:00:00")
        self.position_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_label = QLabel("STOPPED")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        playback_layout.addWidget(self.title_label)
        playback_layout.addWidget(self.artist_label)
        playback_layout.addWidget(self.album_label)
        playback_layout.addWidget(self.position_label)
        playback_layout.addWidget(self.state_label)
        
        playback_group.setLayout(playback_layout)
        self.main_layout.addWidget(playback_group)
        
        # Media Controls Section
        controls_group = QGroupBox("Media Controls")
        controls_layout = QVBoxLayout()
        
        # Media URL
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("Media URL:"))
        self.url_entry = QLineEdit()
        self.url_entry.setToolTip("Enter direct media URL")
        url_layout.addWidget(self.url_entry)
        controls_layout.addLayout(url_layout)
        
        # Time seek controls
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("Seek to:"))
        self.time_entry = QLineEdit()
        self.time_entry.setToolTip("Enter time in HH:MM:SS format")
        self.time_entry.setPlaceholderText("00:00:00")
        time_layout.addWidget(self.time_entry)
        seek_btn = QPushButton("Seek")
        seek_btn.setToolTip("Seek to specified time")
        seek_btn.clicked.connect(self._seek_to_time)
        time_layout.addWidget(seek_btn)
        controls_layout.addLayout(time_layout)
        
        # Playback controls
        playback_btns = QHBoxLayout()
        play_btn = QPushButton("▶ Play")
        play_btn.setToolTip("Play media")
        play_btn.clicked.connect(self._play)
        pause_btn = QPushButton("⏸ Pause")
        pause_btn.setToolTip("Pause playback")
        pause_btn.clicked.connect(self._pause)
        stop_btn = QPushButton("⏹ Stop")
        stop_btn.setToolTip("Stop playback")
        stop_btn.clicked.connect(self._stop)
        
        playback_btns.addWidget(play_btn)
        playback_btns.addWidget(pause_btn)
        playback_btns.addWidget(stop_btn)
        controls_layout.addLayout(playback_btns)
        
        controls_group.setLayout(controls_layout)
        self.main_layout.addWidget(controls_group)
        
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
                                self.receiver_volume.setValue(volume)
                        except (ValueError, TypeError):
                            pass
                            
                elif action == "reset_media_info":
                    self.title_label.setText("No media playing")
                    self.artist_label.setText("")
                    self.album_label.setText("")
                    self.position_label.setText("00:00:00 / 00:00:00")
                    self.state_label.setText("STOPPED")
                    
                elif action == "update_status":
                    if self.status_bar is not None:
                        self.status_bar.showMessage(data)
                    else:
                        logger.warning(f"Status bar not available to show message: {data}")
                    
                elif action == "show_progress":
                    if self.progress_bar is not None:
                        self.progress_bar.setRange(0, 0)  # Indeterminate progress
                        self.progress_bar.show()
                    else:
                        logger.warning("Progress bar not available to show progress")
                    
                elif action == "hide_progress":
                    if self.progress_bar is not None:
                        self.progress_bar.hide()
                        self.progress_bar.setRange(0, 100)  # Reset to determinate
                    else:
                        logger.warning("Progress bar not available to hide")
                    
                elif action == "update_input_sources":
                    self.receiver_input.clear()
                    for source in data['sources']:
                        self.receiver_input.addItem(source)
                    if data.get('current'):
                        self.receiver_input.setCurrentText(data['current'])
                    self.receiver_input.setEnabled(True)
                    
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
                if self.media_controller.set_receiver_power(True):
                    self._update_status_safe(f"Power on command sent to {ip}")
                    logger.info(f"Power on command sent successfully to {ip}")
                else:
                    self._update_status_safe("Failed to power on receiver")
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
                if self.media_controller.set_receiver_power(False):
                    self._update_status_safe(f"Power off command sent to {ip}")
                    logger.info(f"Power off command sent successfully to {ip}")
                else:
                    self._update_status_safe("Failed to power off receiver")
            else:
                self._update_status_safe("Failed to find renderer IP")
        except Exception as e:
            error_msg = f"Error powering off renderer: {e}"
            logger.error(error_msg, exc_info=True)
            self._update_status_safe(error_msg)
    
    def _on_input_source_changed(self, source):
        """Handle input source changes."""
        if source and self.media_controller.receiver:
            if self.media_controller.set_receiver_input(source):
                self._update_status_safe(f"Input source changed to {source}")
            else:
                self._update_status_safe(f"Failed to change input source to {source}")
                # Get current input from receiver
                inputs = self.media_controller.get_receiver_inputs()
                if inputs:
                    self.receiver_input.setCurrentText(inputs[0])  # Set to first available input
    
    def _update_status_safe(self, message: str) -> None:
        """Safely update status bar message."""
        if self.status_bar is not None:
            self.status_bar.showMessage(message)
        else:
            logger.warning(f"Status bar not available to show message: {message}")
    
    def play_soundcloud(self):
        """Play a Soundcloud URL."""
        url = self.url_input.text()
        if url and url != "Enter Soundcloud/Youtube URL...":
            if self.media_controller.play_soundcloud(url):
                self._update_status_safe(f"Playing Soundcloud track: {url}")
            else:
                self._update_status_safe("Failed to play Soundcloud track")
    
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
            
            # Clear existing devices
            server_dicts: List[DeviceDict] = []
            renderer_dicts: List[DeviceDict] = []
            
            # Discover all devices first
            self.media_controller.discovery.discover_devices()
            
            # Get discovered devices
            servers = self.media_controller.discovery.get_media_servers()
            renderers = self.media_controller.discovery.get_media_renderers()
            
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
                    continue
            
            # Update UI with discovered devices
            self._update_device_lists(server_dicts, renderer_dicts)
            
            # Save discovered devices
            if server_dicts or renderer_dicts:
                if self.device_storage.save_devices(server_dicts, renderer_dicts):
                    logger.info(f"Saved {len(server_dicts)} servers and {len(renderer_dicts)} renderers to storage")
                else:
                    logger.error("Failed to save devices to storage")
            
            # Update status
            if not server_dicts and not renderer_dicts:
                self._update_status_safe("No devices found")
            else:
                self._update_status_safe(f"Found {len(server_dicts)} servers and {len(renderer_dicts)} renderers")
                
        except Exception as e:
            logger.error(f"Error during discovery: {e}", exc_info=True)
            self.update_queue.put(("discovery_error", str(e)))
        finally:
            # Hide progress bar
            self.update_queue.put(("hide_progress", None))

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
    
    def _on_renderer_selected(self, renderer_name: str):
        """Handle renderer selection."""
        if renderer_name:
            try:
                renderers = discover_media_renderers()
                for renderer in renderers:
                    if isinstance(renderer, dict):
                        if renderer['friendly_name'] == renderer_name:
                            if self.media_controller.set_renderer(renderer):
                                self._update_receiver_controls()
                                self._update_status_safe(f"Connected to {renderer_name}")
                            return
                    else:
                        if renderer.friendly_name == renderer_name:
                            if self.media_controller.set_renderer(renderer):
                                self._update_receiver_controls()
                                self._update_status_safe(f"Connected to {renderer_name}")
                            return
                
                self._update_status_safe("Failed to find selected renderer")
            except Exception as e:
                error_msg = f"Error selecting renderer: {e}"
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
                self._update_status_safe("No items found")
                return
                
            # Parse and display results
            for item in result:
                list_item = QListWidgetItem()
                
                # Set icon based on type
                style = self.style()
                if style is not None:
                    if item.get("type") == "container":
                        list_item.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DirIcon))
                    else:
                        list_item.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileIcon))
                else:
                    logger.warning("Style not available for setting icons")
                
                # Set item text and data
                list_item.setText(item.get("title", "Unknown"))
                list_item.setData(Qt.ItemDataRole.UserRole, item)
                
                self.content_list.addItem(list_item)
                
            self._update_status_safe(f"Found {self.content_list.count()} items")
        except Exception as e:
            error_msg = f"Error browsing container: {e}"
            logger.error(error_msg, exc_info=True)
            self._update_status_safe(error_msg)
    
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
            
            # Discover all devices first
            self.media_controller.discovery.discover_devices()
            
            # Get discovered devices
            servers = self.media_controller.discovery.get_media_servers()
            renderers = self.media_controller.discovery.get_media_renderers()
            
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
                    continue
            
            # Update UI with discovered devices
            self._update_device_lists(server_dicts, renderer_dicts)
            
            # Save discovered devices
            if server_dicts or renderer_dicts:
                if self.device_storage.save_devices(server_dicts, renderer_dicts):
                    logger.info(f"Saved {len(server_dicts)} servers and {len(renderer_dicts)} renderers to storage")
                else:
                    logger.error("Failed to save devices to storage")
            
            # Update status
            if not server_dicts and not renderer_dicts:
                self._update_status_safe("No devices found")
            else:
                self._update_status_safe(f"Found {len(server_dicts)} servers and {len(renderer_dicts)} renderers")
                
        except Exception as e:
            error_msg = f"Error during device discovery: {e}"
            logger.error(error_msg, exc_info=True)
            self._update_status_safe(error_msg)
        finally:
            # Hide progress bar
            self.update_queue.put(("hide_progress", None))

    def _on_content_source_changed(self, source: str):
        """Handle content source selection change."""
        # Hide all inputs first
        self.file_input.hide()
        self.url_widget.hide()
        self.content_list.hide()
        self.path_label.hide()
        
        # Show relevant inputs based on selection
        if source == "Media Server":
            self.content_list.show()
            self.path_label.show()
            self._browse_container(self.current_container_id)
        elif source == "Local File":
            self.file_input.show()
        elif source == "Soundcloud/Youtube":
            self.url_widget.show()

    def play_url(self):
        """Handle URL playback."""
        url = self.url_input.text()
        if not url:
            self._update_status_safe("Please enter a URL")
            return
        
        if "soundcloud.com" in url.lower():
            self.media_controller.play_soundcloud(url)
        else:
            # Handle YouTube URLs or direct media URLs
            self.url_entry.setText(url)
            self._play()

    def _connect_receiver(self):
        """Connect to receiver using IP address."""
        ip_address = self.receiver_ip_input.text().strip()
        if not ip_address:
            self._update_status_safe("Please enter an IP address")
            return
            
        try:
            if self.media_controller.set_renderer({'location': f'http://{ip_address}', 'manufacturer': 'Yamaha'}):
                self._update_status_safe(f"Connected to receiver at {ip_address}")
                self._update_receiver_controls()
            else:
                self._update_status_safe("Failed to connect to receiver")
        except Exception as e:
            error_msg = f"Error connecting to receiver: {e}"
            logger.error(error_msg, exc_info=True)
            self._update_status_safe(error_msg)

    def _update_receiver_controls(self):
        """Update receiver controls with current state."""
        if self.media_controller.receiver:
            try:
                status = self.media_controller.receiver.get_status()
                
                # Update power state
                power = status.get('power', False)
                self._update_status_safe("Power: " + ("On" if power else "Off"))
                
                # Update volume
                volume = status.get('volume', 0)
                self.receiver_volume.setValue(volume)
                
                # Update input source
                current_input = status.get('input', '')
                input_list = self.media_controller.receiver.get_input_list()
                self.receiver_input.clear()
                self.receiver_input.addItems(input_list)
                if current_input in input_list:
                    self.receiver_input.setCurrentText(current_input)
                
                # Update mute state
                mute = status.get('mute', False)
                self.receiver_mute.setChecked(mute)
                
            except Exception as e:
                logger.error(f"Error updating receiver controls: {e}")
                self._update_status_safe("Error updating receiver status")

    def _set_receiver_power(self, power: bool):
        """Set receiver power state."""
        if self.media_controller.receiver:
            if self.media_controller.receiver.set_power(power):
                self._update_status_safe(f"Power {'On' if power else 'Off'}")
                self._update_receiver_controls()
            else:
                self._update_status_safe("Failed to set power state")

    def _on_receiver_volume_change(self, value: int):
        """Handle volume slider changes."""
        if self.media_controller.receiver:
            if self.media_controller.receiver.set_volume(value):
                self._update_status_safe(f"Volume: {value}")
            else:
                self._update_status_safe("Failed to set volume")

    def _on_receiver_input_change(self, input_source: str):
        """Handle input source changes."""
        if input_source and self.media_controller.receiver:
            if self.media_controller.receiver.set_input(input_source):
                self._update_status_safe(f"Input: {input_source}")
            else:
                self._update_status_safe("Failed to set input source")

    def _on_receiver_mute_toggle(self, checked: bool):
        """Handle mute button toggle."""
        if self.media_controller.receiver:
            if self.media_controller.receiver.set_mute(checked):
                self._update_status_safe(f"{'Muted' if checked else 'Unmuted'}")
            else:
                self._update_status_safe("Failed to set mute state")

    def _update_input_sources(self, data):
        """Update input sources in the UI."""
        if 'sources' in data:
            self.receiver_input.clear()
            for source in data['sources']:
                self.receiver_input.addItem(source)
            if data.get('current'):
                self.receiver_input.setCurrentText(data['current'])
            self.receiver_input.setEnabled(True)