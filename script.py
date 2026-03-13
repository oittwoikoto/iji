"""
Production-ready Twitch viewer automation script.
Uses SeleniumBase for undetectable browser automation.
"""

import base64
import logging
import random
import time
from typing import Optional, Dict, Tuple
from dataclasses import dataclass
from pathlib import Path
import json

import requests
from seleniumbase import SB

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('twitch_viewer.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class GeoLocation:
    """Stores geolocation data"""
    latitude: float
    longitude: float
    timezone: str
    country_code: str


@dataclass
class Config:
    """Configuration settings for the script"""
    target_channel: str
    use_proxy: bool = False
    sleep_min: int = 450
    sleep_max: int = 800
    max_retries: int = 3
    request_timeout: int = 10
    
    @classmethod
    def from_json(cls, filepath: str) -> 'Config':
        """Load configuration from JSON file"""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            return cls(**data)
        except FileNotFoundError:
            logger.warning(f"Config file {filepath} not found. Using defaults.")
            return cls(target_channel="brutallles")
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            raise


class GeoLocationService:
    """Handles geolocation retrieval"""
    
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.api_url = "http://ip-api.com/json/"
    
    def get_location(self) -> Optional[GeoLocation]:
        """Fetch geolocation data from IP API"""
        try:
            logger.info("Fetching geolocation data...")
            response = requests.get(self.api_url, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('status') != 'success':
                logger.error(f"Geolocation API error: {data.get('message')}")
                return None
            
            geo = GeoLocation(
                latitude=data.get('lat'),
                longitude=data.get('lon'),
                timezone=data.get('timezone'),
                country_code=data.get('countryCode', '').lower()
            )
            logger.info(f"Geolocation: {geo.country_code}, TZ: {geo.timezone}")
            return geo
            
        except requests.RequestException as e:
            logger.error(f"Failed to fetch geolocation: {e}")
            return None


class TwitchViewer:
    """Main Twitch viewer automation class"""
    
    def __init__(self, config: Config, geo: GeoLocation):
        self.config = config
        self.geo = geo
        self.channel_url = self._build_channel_url()
        self.retry_count = 0
    
    def _build_channel_url(self) -> str:
        """Build Twitch channel URL from base64 encoded or plain channel name"""
        try:
            # Try to decode as base64
            decoded = base64.b64decode(self.config.target_channel).decode('utf-8')
            return f"https://www.twitch.tv/{decoded}"
        except Exception:
            # If decoding fails, use as-is
            return f"https://www.twitch.tv/{self.config.target_channel}"
    
    def _accept_if_present(self, driver, timeout: int = 4) -> bool:
        """Helper to click Accept button if present"""
        try:
            if driver.is_element_present('button:contains("Accept")'):
                driver.cdp.click('button:contains("Accept")', timeout=timeout)
                logger.debug("Clicked Accept button")
                return True
        except Exception as e:
            logger.debug(f"Error clicking Accept: {e}")
        return False
    
    def _start_watching_if_present(self, driver, timeout: int = 4) -> bool:
        """Helper to click Start Watching button if present"""
        try:
            if driver.is_element_present('button:contains("Start Watching")'):
                driver.cdp.click('button:contains("Start Watching")', timeout=timeout)
                logger.debug("Clicked Start Watching button")
                return True
        except Exception as e:
            logger.debug(f"Error clicking Start Watching: {e}")
        return False
    
    def _activate_viewer(self, driver) -> bool:
        """Activate viewer on the channel"""
        try:
            driver.sleep(2)
            self._accept_if_present(driver)
            driver.sleep(2)
            driver.sleep(12)
            self._start_watching_if_present(driver)
            driver.sleep(10)
            self._accept_if_present(driver)
            return True
        except Exception as e:
            logger.error(f"Error activating viewer: {e}")
            return False
    
    def _check_live_stream(self, driver) -> bool:
        """Check if live stream information is present"""
        try:
            return driver.is_element_present("#live-channel-stream-information")
        except Exception as e:
            logger.debug(f"Error checking live stream: {e}")
            return False
    
    def run_cycle(self) -> bool:
        """Run a single viewing cycle"""
        try:
            with SB(
                uc=True,
                locale="en",
                ad_block=True,
                chromium_arg='--disable-webgl',
                proxy=self.config.use_proxy
            ) as driver:
                logger.info(f"Starting viewing cycle for {self.channel_url}")
                
                # Activate main driver
                driver.activate_cdp_mode(
                    self.channel_url,
                    tzone=self.geo.timezone,
                    geoloc=(self.geo.latitude, self.geo.longitude)
                )
                
                if not self._activate_viewer(driver):
                    logger.warning("Failed to activate main viewer")
                    return False
                
                # Check if stream is live
                if self._check_live_stream(driver):
                    logger.info("Live stream detected")
                    self._accept_if_present(driver)
                    
                    # Create secondary driver
                    try:
                        driver2 = driver.get_new_driver(undetectable=True)
                        driver2.activate_cdp_mode(
                            self.channel_url,
                            tzone=self.geo.timezone,
                            geoloc=(self.geo.latitude, self.geo.longitude)
                        )
                        driver2.sleep(10)
                        self._start_watching_if_present(driver2)
                        driver2.sleep(10)
                        self._accept_if_present(driver2)
                        
                        # Main sleep
                        sleep_duration = random.randint(self.config.sleep_min, self.config.sleep_max)
                        logger.info(f"Watching for {sleep_duration} seconds")
                        driver.sleep(sleep_duration)
                        
                    except Exception as e:
                        logger.error(f"Error with secondary driver: {e}")
                    
                    self.retry_count = 0
                    return True
                else:
                    logger.info("Stream not live, ending cycle")
                    return False
                    
        except Exception as e:
            logger.error(f"Error in viewing cycle: {e}")
            self.retry_count += 1
            return False
    
    def run(self, max_cycles: Optional[int] = None):
        """Run the viewer in a loop"""
        cycle_count = 0
        try:
            while max_cycles is None or cycle_count < max_cycles:
                if self.retry_count >= self.config.max_retries:
                    logger.error("Max retries exceeded, stopping")
                    break
                
                success = self.run_cycle()
                cycle_count += 1
                
                if not success:# and self.retry_count >= self.config.max_retries:
                    break
                
                # Brief pause between cycles
                time.sleep(5)
                
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.error(f"Fatal error in main loop: {e}")


# Test Functions
def test_geolocation_service():
    """Test geolocation service"""
    logger.info("Testing geolocation service...")
    service = GeoLocationService(timeout=10)
    geo = service.get_location()
    assert geo is not None, "Failed to retrieve geolocation"
    assert geo.latitude is not None, "Latitude is None"
    assert geo.longitude is not None, "Longitude is None"
    assert geo.timezone, "Timezone is empty"
    logger.info("✓ Geolocation test passed")


def test_config_loading():
    """Test configuration loading"""
    logger.info("Testing config loading...")
    config = Config.from_json("config.json")
    assert config.target_channel, "Channel name is empty"
    assert config.sleep_min > 0, "Sleep min should be positive"
    assert config.sleep_max > config.sleep_min, "Sleep max should be greater than min"
    logger.info("✓ Config test passed")


def test_channel_url_building():
    """Test channel URL building"""
    logger.info("Testing channel URL building...")
    
    # Test with base64 encoded name
    config = Config(target_channel="YnJ1dGFsbGVz")  # "brutallles" in base64
    geo = GeoLocation(0, 0, "UTC", "us")
    viewer = TwitchViewer(config, geo)
    
    assert "brutallles" in viewer.channel_url, "Failed to decode base64 channel name"
    assert viewer.channel_url.startswith("https://www.twitch.tv/"), "Invalid URL format"
    logger.info("✓ Channel URL building test passed")


def run_all_tests():
    """Run all test functions"""
    logger.info("="*50)
    logger.info("Running test suite...")
    logger.info("="*50)
    
    tests = [
        test_config_loading,
        test_channel_url_building,
        # test_geolocation_service,  # Uncomment if you have internet access
    ]
    
    for test in tests:
        try:
            test()
        except AssertionError as e:
            logger.error(f"✗ {test.__name__} failed: {e}")
        except Exception as e:
            logger.error(f"✗ {test.__name__} error: {e}")
    
    logger.info("="*50)
    logger.info("Test suite completed")
    logger.info("="*50)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        run_all_tests()
    else:
        try:
            # Load configuration
            config = Config.from_json("config.json")
            
            # Get geolocation
            geo_service = GeoLocationService()
            geo = geo_service.get_location()
            
            if geo is None:
                logger.error("Failed to get geolocation. Using defaults.")
                geo = GeoLocation(latitude=0, longitude=0, timezone="UTC", country_code="us")
            
            # Run viewer
            viewer = TwitchViewer(config, geo)
            viewer.run()
            
        except Exception as e:
            logger.error(f"Fatal error: {e}")
            exit(1)
