"""
Webhook URL registration with cloud app.
"""

import requests
from typing import Tuple
from urllib.parse import urlparse
from .exceptions import WebhookRegistrationError


class WebhookRegistrar:
    """Handles webhook URL registration with cloud app."""
    
    def __init__(self, cloud_base_url: str, api_key: str):
        """
        Initialize registrar.
        
        Args:
            cloud_base_url: Base URL of cloud app
            api_key: API key for authentication
        """
        self.cloud_base_url = cloud_base_url.rstrip('/')
        self.api_key = api_key
    
    def _construct_webhook_url(self, tunnel_url: str) -> str:
        """
        Construct webhook URL by appending /api/webhook to tunnel URL.
        
        Args:
            tunnel_url: Public tunnel URL
            
        Returns:
            Full webhook URL
        """
        tunnel_url = tunnel_url.rstrip('/')
        return f"{tunnel_url}/api/webhook"
    
    def _validate_webhook_url(self, webhook_url: str) -> Tuple[bool, str]:
        """
        Validate webhook URL format.
        
        Args:
            webhook_url: Webhook URL to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            parsed = urlparse(webhook_url)
            
            # must be HTTPS
            if parsed.scheme != 'https':
                return False, "Webhook URL must use HTTPS protocol"
            
            # must have a valid domain
            if not parsed.netloc:
                return False, "Webhook URL must have a valid domain"
            
            # must have a path
            if not parsed.path or parsed.path == '/':
                return False, "Webhook URL must include /api/webhook path"
            
            return True, ""
            
        except Exception as e:
            return False, f"Invalid URL format: {str(e)}"
    
    def register(self, tunnel_url: str, webhook_secret: str = '') -> Tuple[bool, str]:
        """
        Register webhook URL with cloud app.
        
        Args:
            tunnel_url: Public tunnel URL
            webhook_secret: Optional webhook secret for authentication
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # construct webhook URL
            webhook_url = self._construct_webhook_url(tunnel_url)
            
            # validate URL format
            is_valid, error_msg = self._validate_webhook_url(webhook_url)
            if not is_valid:
                return False, error_msg
            
            # send registration request to cloud app
            response = requests.post(
                f"{self.cloud_base_url}/api/save_webhook.php",
                json={
                    'webhook_url': webhook_url,
                    'webhook_secret': webhook_secret
                },
                headers={
                    'X-Server-Key': self.api_key,
                    'Content-Type': 'application/json'
                },
                timeout=10
            )
            
            # handle response
            if response.status_code == 200:
                return True, "Webhook registered successfully"
            elif response.status_code == 401:
                return False, "Authentication failed, check your API key"
            elif response.status_code == 400:
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', 'Invalid request')
                    return False, f"Registration failed: {error_msg}"
                except:
                    return False, "Registration failed: Invalid request"
            elif response.status_code >= 500:
                return False, "Cloud app is experiencing issues, will retry automatically"
            else:
                return False, f"Registration failed with status {response.status_code}"
                
        except requests.exceptions.Timeout:
            return False, "Connection timeout, will retry automatically"
        except requests.exceptions.ConnectionError:
            return False, "Cannot reach cloud app, check your internet connection"
        except Exception as e:
            return False, f"Registration error: {str(e)}"
    
    def test_connection(self, timeout: int = 30) -> Tuple[bool, str]:
        """
        Test webhook connectivity by triggering a test from the cloud app.
        
        Args:
            timeout: Timeout in seconds for the test
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # send test request to cloud app
            response = requests.post(
                f"{self.cloud_base_url}/api/test_webhook.php",
                headers={
                    'X-Server-Key': self.api_key,
                    'Content-Type': 'application/json'
                },
                timeout=timeout
            )
            
            # handle response
            if response.status_code == 200:
                try:
                    data = response.json()
                    if data.get('status') == 'success':
                        duration = data.get('duration_ms', 0)
                        return True, f"Connection test successful ({duration}ms)"
                    else:
                        error_msg = data.get('message', 'Test failed')
                        return False, error_msg
                except:
                    return True, "Connection test successful"
            elif response.status_code == 401:
                return False, "Authentication failed, check your API key"
            elif response.status_code == 400:
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message', 'No webhook URL configured')
                    return False, error_msg
                except:
                    return False, "Test failed: No webhook URL configured"
            else:
                return False, f"Test failed with status {response.status_code}"
                
        except requests.exceptions.Timeout:
            return False, "Connection test timed out (tunnel may be down)"
        except requests.exceptions.ConnectionError:
            return False, "Cannot reach cloud app, check your internet connection"
        except Exception as e:
            return False, f"Test error: {str(e)}"
    
    def unregister(self) -> Tuple[bool, str]:
        """
        Clear webhook URL from cloud app.
        
        Returns:
            Tuple of (success, message)
        """
        try:
            # send empty webhook URL to clear registration
            response = requests.post(
                f"{self.cloud_base_url}/api/save_webhook.php",
                json={
                    'webhook_url': '',
                    'webhook_secret': ''
                },
                headers={
                    'X-Server-Key': self.api_key,
                    'Content-Type': 'application/json'
                },
                timeout=10
            )
            
            # handle response
            if response.status_code == 200:
                return True, "Webhook unregistered successfully"
            elif response.status_code == 401:
                return False, "Authentication failed, check your API key"
            else:
                return False, f"Unregister failed with status {response.status_code}"
                
        except requests.exceptions.Timeout:
            return False, "Connection timeout"
        except requests.exceptions.ConnectionError:
            return False, "Cannot reach cloud app"
        except Exception as e:
            return False, f"Unregister error: {str(e)}"
