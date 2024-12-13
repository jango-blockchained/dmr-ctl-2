"""
Controller module for Yamaha AV receivers using their HTTP/XML API.
"""

import requests
import logging
from typing import Optional, Dict, List
from xml.etree import ElementTree as ET
from .receiver_controller import BaseReceiverController

logger = logging.getLogger(__name__)

class YamahaController(BaseReceiverController):
    def __init__(self, ip_address):
        self.ip_address = ip_address
        self.base_url = f"http://{ip_address}/YamahaRemoteControl/ctrl"
        self.headers = {
            'Content-Type': 'text/xml'
        }

    def _send_command(self, xml_payload: str) -> Optional[ET.Element]:
        """Send XML command to receiver and return parsed response"""
        try:
            logger.debug(f"Sending command to {self.base_url}")
            response = requests.post(self.base_url, data=xml_payload, headers=self.headers)
            response.raise_for_status()
            
            # Log only status code and content length
            logger.debug(f"Response status: {response.status_code}, " 
                        f"Content-Length: {len(response.content)}")
            
            return ET.fromstring(response.text)
        except Exception as e:
            logger.error(f"Failed to send command: {e}")
            return None

    def get_device_info(self):
        """Get basic device information"""
        xml = '''
        <YAMAHA_AV cmd="GET">
            <System>
                <Config>GetParam</Config>
            </System>
        </YAMAHA_AV>
        '''
        return self._send_command(xml)

    def get_status(self) -> Dict:
        """Get the current status of the device"""
        xml = '''
        <YAMAHA_AV cmd="GET">
            <Main_Zone>
                <Basic_Status>GetParam</Basic_Status>
            </Main_Zone>
        </YAMAHA_AV>
        '''
        try:
            root = self._send_command(xml)
            if root is None:
                return {}

            status = {}
            main_zone = root.find('.//Main_Zone')
            if main_zone is not None:
                # Get power status
                power = main_zone.find('.//Power')
                status['power'] = power.text == 'On' if power is not None else False

                # Get volume - convert from Yamaha's -800 to 0 scale to 0-100
                volume = main_zone.find('.//Volume/Lvl/Val')
                if volume is not None:
                    yamaha_vol = int(volume.text)
                    status['volume'] = int((yamaha_vol + 800) / 800 * 100)
                else:
                    status['volume'] = 0

                # Get input
                input_elem = main_zone.find('.//Input/Input_Sel')
                status['input'] = input_elem.text if input_elem is not None else ''

                # Get mute status
                mute = main_zone.find('.//Volume/Mute')
                status['mute'] = mute.text == 'On' if mute is not None else False

            return status
        except Exception as e:
            logger.error(f"Failed to parse status: {e}")
            return {}

    def set_power(self, power: bool) -> bool:
        """Turn the device on or off"""
        state = "On" if power else "Standby"
        xml = f'''
        <YAMAHA_AV cmd="PUT">
            <Main_Zone>
                <Power_Control>
                    <Power>{state}</Power>
                </Power_Control>
            </Main_Zone>
        </YAMAHA_AV>
        '''
        return self._send_command(xml) is not None

    def set_volume(self, volume: int) -> bool:
        """Set volume level (0-100)"""
        try:
            # Convert 0-100 scale to Yamaha's -800 to 0 scale
            yamaha_volume = int((volume / 100) * 800 - 800)
            xml = f'''
            <YAMAHA_AV cmd="PUT">
                <Main_Zone>
                    <Volume>
                        <Lvl>
                            <Val>{yamaha_volume}</Val>
                            <Exp>1</Exp>
                            <Unit>dB</Unit>
                        </Lvl>
                    </Volume>
                </Main_Zone>
            </YAMAHA_AV>
            '''
            return self._send_command(xml) is not None
        except Exception as e:
            logger.error(f"Failed to set volume: {e}")
            return False

    def set_input(self, input_source: str) -> bool:
        """Set input source (e.g., 'HDMI1', 'AV1', 'AUDIO')"""
        xml = f'''
        <YAMAHA_AV cmd="PUT">
            <Main_Zone>
                <Input>
                    <Input_Sel>{input_source}</Input_Sel>
                </Input>
            </Main_Zone>
        </YAMAHA_AV>
        '''
        return self._send_command(xml) is not None

    def set_mute(self, mute: bool) -> bool:
        """Set mute state"""
        state = "On" if mute else "Off"
        xml = f'''
        <YAMAHA_AV cmd="PUT">
            <Main_Zone>
                <Volume>
                    <Mute>{state}</Mute>
                </Volume>
            </Main_Zone>
        </YAMAHA_AV>
        '''
        return self._send_command(xml) is not None

    def get_input_list(self) -> List[str]:
        """Get list of available inputs"""
        xml = '''
        <YAMAHA_AV cmd="GET">
            <Main_Zone>
                <Input>
                    <Input_Sel_Item>GetParam</Input_Sel_Item>
                </Input>
            </Main_Zone>
        </YAMAHA_AV>
        '''
        try:
            root = self._send_command(xml)
            if root is None:
                return []
            
            inputs = []
            for item in root.findall('.//Input_Sel_Item/Item'):
                if item.text:
                    inputs.append(item.text)
            return inputs
        except Exception as e:
            logger.error(f"Failed to get input list: {e}")
            return [] 