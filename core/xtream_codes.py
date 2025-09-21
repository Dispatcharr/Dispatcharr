import requests
import logging
import traceback
import json

logger = logging.getLogger(__name__)

class Client:
    """Xtream Codes API Client with robust error handling"""

    def __init__(self, server_url, username, password, user_agent=None):
        self.server_url = self._normalize_url(server_url)
        self.username = username
        self.password = password
        self.user_agent = user_agent

        # Fix: Properly handle all possible user_agent input types
        if user_agent:
            if isinstance(user_agent, str):
                user_agent_string = user_agent
            elif hasattr(user_agent, 'user_agent'):
                user_agent_string = user_agent.user_agent
            else:
                logger.warning(f"Unexpected user_agent type: {type(user_agent)}, using default")
                user_agent_string = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        else:
            user_agent_string = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'

        # Create persistent session
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': user_agent_string})

        # Configure connection pooling
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=1,
            pool_maxsize=2,
            max_retries=3,
            pool_block=False
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

        self.server_info = None

    def _normalize_url(self, url):
        """Normalize server URL by removing trailing slashes and paths"""
        if not url:
            raise ValueError("Server URL cannot be empty")

        url = url.rstrip('/')
        # Remove any path after domain - we'll construct proper API URLs
        # Split by protocol first to preserve it
        if '://' in url:
            protocol, rest = url.split('://', 1)
            domain = rest.split('/', 1)[0]
            return f"{protocol}://{domain}"
        return url

    def _make_request(self, endpoint, params=None):
        """Make request with detailed error handling"""
        try:
            url = f"{self.server_url}/{endpoint}"
            logger.debug(f"XC API Request: {url} with params: {params}")

            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()

            # Check if response is empty
            if not response.content:
                error_msg = f"XC API returned empty response from {url}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            # Check for common blocking responses before trying to parse JSON
            response_text = response.text.strip()
            if response_text.lower() in ['blocked', 'forbidden', 'access denied', 'unauthorized']:
                error_msg = f"XC API request blocked by server from {url}. Response: {response_text}"
                logger.error(error_msg)
                logger.error(f"This may indicate IP blocking, User-Agent filtering, or rate limiting")
                raise ValueError(error_msg)

            try:
                data = response.json()
            except requests.exceptions.JSONDecodeError as json_err:
                error_msg = f"XC API returned invalid JSON from {url}. Response: {response.text[:1000]}"
                logger.error(error_msg)
                logger.error(f"JSON decode error: {str(json_err)}")

                # Check if it looks like an HTML error page
                if response_text.startswith('<'):
                    logger.error("Response appears to be HTML - server may be returning an error page")

                raise ValueError(error_msg)

            # Check for XC-specific error responses
            if isinstance(data, dict) and data.get('user_info') is None and 'error' in data:
                error_msg = f"XC API Error: {data.get('error', 'Unknown error')}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            return data
        except requests.RequestException as e:
            error_msg = f"XC API Request failed: {str(e)}"
            logger.error(error_msg)
            logger.error(f"Request details: URL={url}, Params={params}")
            raise
        except ValueError as e:
            # This could be from JSON parsing or our explicit raises
            logger.error(f"XC API Invalid response: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"XC API Unexpected error: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def authenticate(self):
        """Authenticate and validate server response"""
        try:
            endpoint = "player_api.php"
            params = {
                'username': self.username,
                'password': self.password
            }

            self.server_info = self._make_request(endpoint, params)

            if not self.server_info or not self.server_info.get('user_info'):
                error_msg = "Authentication failed: Invalid response from server"
                logger.error(f"{error_msg}. Response: {self.server_info}")
                raise ValueError(error_msg)

            logger.info(f"XC Authentication successful for user {self.username}")
            return self.server_info
        except Exception as e:
            logger.error(f"XC Authentication failed: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def get_account_info(self):
        """Get account information from the last authentication response"""
        if not self.server_info:
            raise ValueError("Not authenticated. Call authenticate() first.")

        from datetime import datetime

        # Extract relevant account information
        user_info = self.server_info.get('user_info', {})
        server_info = self.server_info.get('server_info', {})

        account_info = {
            'last_refresh': datetime.utcnow().isoformat() + 'Z',  # Explicit UTC with Z suffix
            'auth_timestamp': datetime.utcnow().timestamp(),
            'user_info': {
                'username': user_info.get('username'),
                'password': user_info.get('password'),
                'message': user_info.get('message'),
                'auth': user_info.get('auth'),
                'status': user_info.get('status'),
                'exp_date': user_info.get('exp_date'),
                'is_trial': user_info.get('is_trial'),
                'active_cons': user_info.get('active_cons'),
                'created_at': user_info.get('created_at'),
                'max_connections': user_info.get('max_connections'),
                'allowed_output_formats': user_info.get('allowed_output_formats', [])
            },
            'server_info': {
                'url': server_info.get('url'),
                'port': server_info.get('port'),
                'https_port': server_info.get('https_port'),
                'server_protocol': server_info.get('server_protocol'),
                'rtmp_port': server_info.get('rtmp_port'),
                'timezone': server_info.get('timezone'),
                'timestamp_now': server_info.get('timestamp_now'),
                'time_now': server_info.get('time_now')
            }
        }

        return account_info

    def get_live_categories(self):
        """Get live TV categories"""
        try:
            if not self.server_info:
                self.authenticate()

            endpoint = "player_api.php"
            params = {
                'username': self.username,
                'password': self.password,
                'action': 'get_live_categories'
            }

            categories = self._make_request(endpoint, params)

            if not isinstance(categories, list):
                error_msg = f"Invalid categories response: {categories}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            logger.info(f"Successfully retrieved {len(categories)} live categories")
            logger.debug(f"Categories: {json.dumps(categories[:5])}...")
            return categories
        except Exception as e:
            logger.error(f"Failed to get live categories: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def get_live_category_streams(self, category_id):
        """Get streams for a specific category"""
        try:
            if not self.server_info:
                self.authenticate()

            endpoint = "player_api.php"
            params = {
                'username': self.username,
                'password': self.password,
                'action': 'get_live_streams',
                'category_id': category_id
            }

            streams = self._make_request(endpoint, params)

            if not isinstance(streams, list):
                error_msg = f"Invalid streams response for category {category_id}: {streams}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            logger.info(f"Successfully retrieved {len(streams)} streams for category {category_id}")
            return streams
        except Exception as e:
            logger.error(f"Failed to get streams for category {category_id}: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def get_all_live_streams(self):
        """Get all live streams (no category filter)"""
        try:
            if not self.server_info:
                self.authenticate()

            endpoint = "player_api.php"
            params = {
                'username': self.username,
                'password': self.password,
                'action': 'get_live_streams'
                # No category_id = get all streams
            }

            streams = self._make_request(endpoint, params)

            if not isinstance(streams, list):
                error_msg = f"Invalid streams response for all live streams: {streams}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            logger.info(f"Successfully retrieved {len(streams)} total live streams")
            return streams
        except Exception as e:
            logger.error(f"Failed to get all live streams: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def get_stream_url(self, stream_id):
        """Get the playback URL for a stream"""
        return f"{self.server_url}/live/{self.username}/{self.password}/{stream_id}.ts"

    def get_episode_stream_url(self, stream_id, container_extension='mp4'):
        """Get the playback URL for an episode stream"""
        return f"{self.server_url}/series/{self.username}/{self.password}/{stream_id}.{container_extension}"

    def get_vod_stream_url(self, stream_id, container_extension='mp4'):
        """Get the playback URL for a VOD stream"""
        return f"{self.server_url}/movie/{self.username}/{self.password}/{stream_id}.{container_extension}"

    def get_vod_categories(self):
        """Get VOD categories"""
        try:
            if not self.server_info:
                self.authenticate()

            endpoint = "player_api.php"
            params = {
                'username': self.username,
                'password': self.password,
                'action': 'get_vod_categories'
            }

            categories = self._make_request(endpoint, params)

            if not isinstance(categories, list):
                error_msg = f"Invalid VOD categories response: {categories}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            logger.info(f"Successfully retrieved {len(categories)} VOD categories")
            return categories
        except Exception as e:
            logger.error(f"Failed to get VOD categories: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def get_vod_streams(self, category_id=None):
        """Get VOD streams for a specific category"""
        try:
            if not self.server_info:
                self.authenticate()

            endpoint = "player_api.php"
            params = {
                'username': self.username,
                'password': self.password,
                'action': 'get_vod_streams'
            }

            if category_id:
                params['category_id'] = category_id

            streams = self._make_request(endpoint, params)

            if not isinstance(streams, list):
                error_msg = f"Invalid VOD streams response for category {category_id}: {streams}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            logger.info(f"Successfully retrieved {len(streams)} VOD streams for category {category_id}")
            return streams
        except Exception as e:
            logger.error(f"Failed to get VOD streams for category {category_id}: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def get_vod_info(self, vod_id):
        """Get detailed information for a specific VOD"""
        try:
            if not self.server_info:
                self.authenticate()

            endpoint = "player_api.php"
            params = {
                'username': self.username,
                'password': self.password,
                'action': 'get_vod_info',
                'vod_id': vod_id
            }

            vod_info = self._make_request(endpoint, params)

            if not isinstance(vod_info, dict):
                error_msg = f"Invalid VOD info response for vod_id {vod_id}: {vod_info}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            logger.info(f"Successfully retrieved VOD info for vod_id {vod_id}")
            return vod_info
        except Exception as e:
            logger.error(f"Failed to get VOD info for vod_id {vod_id}: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def get_series_categories(self):
        """Get series categories"""
        try:
            if not self.server_info:
                self.authenticate()

            endpoint = "player_api.php"
            params = {
                'username': self.username,
                'password': self.password,
                'action': 'get_series_categories'
            }

            categories = self._make_request(endpoint, params)

            if not isinstance(categories, list):
                error_msg = f"Invalid series categories response: {categories}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            logger.info(f"Successfully retrieved {len(categories)} series categories")
            return categories
        except Exception as e:
            logger.error(f"Failed to get series categories: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def get_series(self, category_id=None):
        """Get series for a specific category"""
        try:
            if not self.server_info:
                self.authenticate()

            endpoint = "player_api.php"
            params = {
                'username': self.username,
                'password': self.password,
                'action': 'get_series'
            }

            if category_id:
                params['category_id'] = category_id

            series = self._make_request(endpoint, params)

            if not isinstance(series, list):
                error_msg = f"Invalid series response for category {category_id}: {series}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            logger.info(f"Successfully retrieved {len(series)} series for category {category_id}")
            return series
        except Exception as e:
            logger.error(f"Failed to get series for category {category_id}: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def get_series_info(self, series_id):
        """Get detailed information for a specific series including episodes"""
        try:
            if not self.server_info:
                self.authenticate()

            endpoint = "player_api.php"
            params = {
                'username': self.username,
                'password': self.password,
                'action': 'get_series_info',
                'series_id': series_id
            }

            series_info = self._make_request(endpoint, params)

            if not isinstance(series_info, dict):
                error_msg = f"Invalid series info response for series_id {series_id}: {series_info}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            logger.info(f"Successfully retrieved series info for series_id {series_id}")
            return series_info
        except Exception as e:
            logger.error(f"Failed to get series info for series_id {series_id}: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    def close(self):
        """Close the session and cleanup resources"""
        if hasattr(self, 'session') and self.session:
            try:
                self.session.close()
            except Exception as e:
                logger.debug(f"Error closing XC session: {e}")

    def __enter__(self):
        """Enter the context manager"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the context manager and cleanup resources"""
        self.close()
        return False  # Don't suppress exceptions

    def __del__(self):
        """Ensure session is closed when object is destroyed"""
        self.close()
