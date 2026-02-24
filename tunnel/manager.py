"""
Core tunnel lifecycle management - authentication, creation, process control.
"""

import json
import os
import subprocess
import yaml
from base64 import b64encode, b64decode
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

from .binary import BinaryManager
from .exceptions import (
    AuthenticationError,
    TunnelCreationError,
    ProcessManagementError,
)


class TunnelManager:
    """Manages Cloudflare tunnel lifecycle and operations."""
    
    def __init__(self, app, db):
        """
        Initialize tunnel manager.
        
        Args:
            app: Flask application instance
            db: Database instance
        """
        self.app = app
        self.db = db
        self.process = None  # cloudflared subprocess
        
        # set up config directory paths
        # use app's instance path if available, otherwise fall back to user's home
        if hasattr(app, 'instance_path'):
            base_config_dir = app.instance_path
        else:
            base_config_dir = os.path.expanduser('~/.seekandwatch')
        
        self.config_dir = os.path.join(base_config_dir, 'cloudflare')
        
        # initialize BinaryManager with config directory
        self.binary_manager = BinaryManager(self.config_dir)
    
    def ensure_binary(self) -> bool:
        """
        Download cloudflared binary if not present.
        
        Returns:
            True on success, False otherwise
        """
        try:
            return self.binary_manager.ensure_binary()
        except Exception:
            self.app.logger.error("Failed to ensure cloudflared binary")
            return False
    
    def authenticate(self) -> bool:
        """
        Run Cloudflare authentication flow.
        
        Returns:
            True on success, False otherwise
        """
        try:
            # ensure binary is available before attempting auth
            if not self.ensure_binary():
                raise AuthenticationError("Cloudflared binary not available")
            
            # run the authentication flow
            credentials = self._run_auth_flow()
            
            if not credentials:
                raise AuthenticationError("Authentication flow did not return credentials")
            
            # encrypt credentials before storing
            encrypted_creds = self._encrypt_credentials(credentials)
            
            # store encrypted credentials in database
            # note: this will be called in context of a specific user
            # the calling code should handle updating the user's settings
            return encrypted_creds
            
        except AuthenticationError:
            self.app.logger.error("Authentication failed")
            return False
        except Exception:
            self.app.logger.error("Unexpected error during authentication")
            return False
    
    def get_or_authenticate(self, user_id: int) -> Optional[dict]:
        """
        Get existing credentials or trigger new authentication.
        
        Implements credential reuse logic:
        1. Check for existing encrypted credentials in database
        2. Decrypt and validate credentials
        3. If invalid or missing, trigger re-authentication
        
        Args:
            user_id: User ID to get/set credentials for
            
        Returns:
            Decrypted credentials dict on success, None on failure
        """
        try:
            # import Settings model here to avoid circular imports
            from models import Settings
            
            # get user's settings
            settings = Settings.query.filter_by(user_id=user_id).first()
            
            if not settings:
                raise AuthenticationError(f"Settings not found for user {user_id}")
            
            # check for existing encrypted credentials
            if settings.tunnel_credentials_encrypted:
                # try to decrypt and validate
                credentials = self._decrypt_credentials(settings.tunnel_credentials_encrypted)
                
                if credentials and self._validate_credentials(credentials):
                    # credentials are valid, reuse them
                    self.app.logger.info(f"Reusing existing tunnel credentials for user {user_id}")
                    return credentials
                else:
                    # credentials are invalid or corrupted
                    self.app.logger.warning(f"Existing credentials invalid for user {user_id}, re-authenticating")
            
            # no valid credentials exist, trigger new authentication
            encrypted_creds = self.authenticate()
            
            if not encrypted_creds:
                return None
            
            # store encrypted credentials in database
            settings.tunnel_credentials_encrypted = encrypted_creds
            self.db.session.commit()
            
            # decrypt and return the credentials
            return self._decrypt_credentials(encrypted_creds)
            
        except Exception:
            self.app.logger.error("Failed to get or authenticate credentials")
            return None
    
    def _validate_credentials(self, credentials: dict) -> bool:
        """
        Validate that credentials are well-formed and usable.
        
        Args:
            credentials: Decrypted credentials dict
            
        Returns:
            True if credentials are valid, False otherwise
        """
        if not credentials:
            return False
        
        # check that required fields exist
        if 'cert_content' not in credentials:
            return False
        
        # check that cert content is not empty
        if not credentials['cert_content'] or not credentials['cert_content'].strip():
            return False
        
        # basic validation passed
        # note: we could do more validation here (e.g., try to parse the cert)
        # but for now, basic checks are sufficient
        return True
    
    def create_tunnel(self, user_id: int) -> Optional[str]:
        """
        Create named tunnel.
        
        Implements retry logic with exponential backoff (3 attempts).
        
        Args:
            user_id: User ID for tunnel name generation
            
        Returns:
            Tunnel URL on success, None on failure
            
        Raises:
            TunnelCreationError: If tunnel creation fails after all retries
        """
        import time
        
        # ensure binary is available
        if not self.ensure_binary():
            raise TunnelCreationError("Cloudflared binary not available")
        
        # generate unique tunnel name
        tunnel_name = self._generate_tunnel_name(user_id)
        
        # retry logic with exponential backoff (1s, 2s, 4s)
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                self.app.logger.info(f"Creating tunnel '{tunnel_name}' (attempt {attempt}/{max_attempts})")
                
                # execute cloudflared tunnel create command
                binary_path = self.binary_manager.get_binary_path()
                
                process = subprocess.run(
                    [binary_path, 'tunnel', 'create', tunnel_name],
                    capture_output=True,
                    text=True,
                    timeout=60  # 1 minute timeout
                )
                
                if process.returncode != 0:
                    error_msg = process.stderr.strip() if process.stderr else "Unknown error"
                    raise TunnelCreationError(f"cloudflared tunnel create failed: {error_msg}")
                
                # parse tunnel ID and URL from output
                # output format: "Created tunnel <name> with id <tunnel-id>"
                tunnel_id = None
                tunnel_url = None
                
                for line in process.stdout.split('\n'):
                    if 'Created tunnel' in line and 'with id' in line:
                        # extract tunnel ID from line
                        parts = line.split('with id')
                        if len(parts) >= 2:
                            tunnel_id = parts[1].strip()
                
                if not tunnel_id:
                    raise TunnelCreationError("Failed to parse tunnel ID from cloudflared output")
                
                # get tunnel info to grab the URL
                info_process = subprocess.run(
                    [binary_path, 'tunnel', 'info', tunnel_id],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if info_process.returncode == 0:
                    # parse tunnel URL from info output
                    # for now, we'll construct it based on the tunnel ID
                    # cloudflare assigns URLs like: https://<tunnel-id>.cfargotunnel.com
                    tunnel_url = f"https://{tunnel_id}.cfargotunnel.com"
                else:
                    # fallback: construct URL from tunnel ID
                    tunnel_url = f"https://{tunnel_id}.cfargotunnel.com"
                
                # create tunnel configuration
                config = self._create_tunnel_config(tunnel_name, tunnel_url)
                
                # write config file
                config_path = self._write_config_file(config, tunnel_id)
                
                # store tunnel configuration in database
                from models import Settings
                settings = Settings.query.filter_by(user_id=user_id).first()
                
                if not settings:
                    raise TunnelCreationError(f"Settings not found for user {user_id}")
                
                settings.tunnel_name = tunnel_name
                settings.tunnel_url = tunnel_url
                settings.tunnel_status = 'connected'
                self.db.session.commit()
                
                self.app.logger.info(f"Successfully created tunnel '{tunnel_name}' with URL {tunnel_url}")
                return tunnel_url
                
            except subprocess.TimeoutExpired:
                error_msg = f"Tunnel creation timed out (attempt {attempt}/{max_attempts})"
                self.app.logger.warning(error_msg)
                
                if attempt < max_attempts:
                    # exponential backoff: 1s, 2s, 4s
                    delay = 2 ** (attempt - 1)
                    self.app.logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    raise TunnelCreationError(error_msg)
                    
            except subprocess.SubprocessError:
                error_msg = f"Failed to run cloudflared tunnel create (attempt {attempt}/{max_attempts})"
                self.app.logger.warning(error_msg)
                
                if attempt < max_attempts:
                    delay = 2 ** (attempt - 1)
                    self.app.logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    raise TunnelCreationError(error_msg)
                    
            except TunnelCreationError:
                # tunnel creation error (parsing, database, etc.)
                self.app.logger.warning(f"Tunnel creation error (attempt {attempt}/{max_attempts})")
                
                if attempt < max_attempts:
                    delay = 2 ** (attempt - 1)
                    self.app.logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    raise
                    
            except Exception:
                error_msg = f"Unexpected error during tunnel creation (attempt {attempt}/{max_attempts})"
                self.app.logger.error(error_msg)
                
                if attempt < max_attempts:
                    delay = 2 ** (attempt - 1)
                    self.app.logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    raise TunnelCreationError(error_msg)
        
        # should never reach here, but just in case
        raise TunnelCreationError("Failed to create tunnel after all retry attempts")
    
    def start_tunnel(self, user_id: int) -> bool:
        """
        Start cloudflared subprocess.
        
        Prevents duplicate process instances and captures stdout/stderr for logging.
        Updates database with tunnel_last_started timestamp.
        
        Args:
            user_id: User ID for database updates
            
        Returns:
            True on success, False otherwise
        """
        try:
            # prevent duplicate process instances
            if self._is_process_running():
                self.app.logger.warning("Cloudflared process already running, not starting duplicate")
                return True  # already running is considered success
            
            # get user settings
            from models import Settings
            settings = Settings.query.filter_by(user_id=user_id).first()
            
            if not settings:
                self.app.logger.error(f"Settings not found for user {user_id}")
                return False
            
            # ensure we have a tunnel name and config
            if not settings.tunnel_name:
                self.app.logger.error("No tunnel name configured, cannot start tunnel")
                return False
            
            # find the config file (should be in config_dir with tunnel name or ID)
            # look for any .yml file in the config directory
            config_path = None
            if os.path.exists(self.config_dir):
                for filename in os.listdir(self.config_dir):
                    if filename.endswith('.yml') or filename.endswith('.yaml'):
                        config_path = os.path.join(self.config_dir, filename)
                        break
            
            if not config_path or not os.path.exists(config_path):
                self.app.logger.error(f"Tunnel config file not found in {self.config_dir}")
                return False
            
            # start the cloudflared process
            self.process = self._start_cloudflared_process(config_path)
            
            if not self.process:
                self.app.logger.error("Failed to start cloudflared process")
                return False
            
            # update database with tunnel_last_started timestamp
            from datetime import datetime
            settings.tunnel_last_started = datetime.utcnow()
            settings.tunnel_status = 'connected'
            self.db.session.commit()
            
            self.app.logger.info(f"Successfully started cloudflared process (PID: {self.process.pid})")
            return True
            
        except Exception:
            self.app.logger.error("Failed to start tunnel")
            
            # update database with error
            try:
                from models import Settings
                settings = Settings.query.filter_by(user_id=user_id).first()
                if settings:
                    settings.tunnel_last_error = "Failed to start tunnel"
                    settings.tunnel_status = 'error'
                    self.db.session.commit()
            except Exception:
                self.app.logger.error("Failed to update database with error")
            
            return False
    
    def stop_tunnel(self, user_id: Optional[int] = None) -> bool:
        """
        Stop cloudflared subprocess gracefully.
        
        Terminates the process with SIGTERM, waits up to 10 seconds,
        then force-kills if necessary. Cleans up resources and updates database.
        
        Args:
            user_id: Optional user ID for database updates
            
        Returns:
            True on success, False otherwise
        """
        try:
            # check if process is running
            if not self._is_process_running():
                self.app.logger.info("No cloudflared process running, nothing to stop")
                return True  # nothing to stop is considered success
            
            # terminate the process gracefully
            success = self._terminate_process(timeout=10)
            
            # update database if user_id provided
            if user_id:
                try:
                    from models import Settings
                    settings = Settings.query.filter_by(user_id=user_id).first()
                    
                    if settings:
                        settings.tunnel_status = 'disconnected'
                        self.db.session.commit()
                        self.app.logger.info(f"Updated tunnel status to disconnected for user {user_id}")
                except Exception as db_error:
                    self.app.logger.error(f"Failed to update database after stopping tunnel: {str(db_error)}")
            
            if success:
                self.app.logger.info("Successfully stopped cloudflared process")
            else:
                self.app.logger.warning("Cloudflared process stopped but may have required force-kill")
            
            return success
            
        except Exception:
            self.app.logger.error("Failed to stop tunnel")
            return False
    
    def register_webhook(self, tunnel_url: str, api_key: str, cloud_base_url: str, user_id: int, webhook_secret: str = '') -> bool:
        """
        Register webhook URL with cloud app.
        
        Implements retry logic: every 5 minutes for 1 hour (12 attempts).
        Updates database status on success/failure.
        
        Args:
            tunnel_url: Public tunnel URL
            api_key: API key for cloud app
            cloud_base_url: Base URL of cloud app
            user_id: User ID for database updates
            webhook_secret: Optional webhook secret for authentication
            
        Returns:
            True on success, False otherwise
        """
        import time
        from datetime import datetime
        
        try:
            # create WebhookRegistrar instance
            from .registrar import WebhookRegistrar
            registrar = WebhookRegistrar(cloud_base_url, api_key)
            
            # retry logic: every 5 minutes for 1 hour (12 attempts)
            max_attempts = 12
            retry_delay = 300  # 5 minutes in seconds
            
            for attempt in range(1, max_attempts + 1):
                self.app.logger.info(f"Attempting webhook registration (attempt {attempt}/{max_attempts})")
                
                # call register() with tunnel URL
                success, message = registrar.register(tunnel_url, webhook_secret)
                
                if success:
                    # update database status on success
                    try:
                        from models import Settings
                        settings = Settings.query.filter_by(user_id=user_id).first()
                        
                        if settings:
                            settings.tunnel_status = 'connected'
                            settings.tunnel_last_error = None
                            settings.cloud_webhook_url = registrar._construct_webhook_url(tunnel_url)
                            self.db.session.commit()
                            
                            self.app.logger.info(f"Webhook registered successfully: {message}")
                        else:
                            self.app.logger.error(f"Settings not found for user {user_id}")
                    except Exception as db_error:
                        self.app.logger.error(f"Failed to update database after successful registration: {str(db_error)}")
                    
                    return True
                
                # registration failed
                self.app.logger.warning(f"Webhook registration failed: {message}")
                
                # update database with error
                try:
                    from models import Settings
                    settings = Settings.query.filter_by(user_id=user_id).first()
                    
                    if settings:
                        settings.tunnel_last_error = f"Registration failed: {message}"
                        
                        # if this is the last attempt, set status to error
                        if attempt >= max_attempts:
                            settings.tunnel_status = 'error'
                        
                        self.db.session.commit()
                except Exception as db_error:
                    self.app.logger.error(f"Failed to update database with registration error: {str(db_error)}")
                
                # if not the last attempt, wait before retrying
                if attempt < max_attempts:
                    self.app.logger.info(f"Will retry in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    self.app.logger.error(f"Webhook registration failed after {max_attempts} attempts")
                    return False
            
            return False
            
        except Exception:
            self.app.logger.error("Unexpected error during webhook registration")
            
            # update database with error
            try:
                from models import Settings
                settings = Settings.query.filter_by(user_id=user_id).first()
                
                if settings:
                    settings.tunnel_last_error = "Registration error"
                    settings.tunnel_status = 'error'
                    self.db.session.commit()
            except Exception:
                self.app.logger.error("Failed to update database with error")
            
            return False
    
    def unregister_webhook(self, api_key: str, cloud_base_url: str, user_id: int) -> bool:
        """
        Unregister webhook URL from cloud app.
        
        Args:
            api_key: API key for cloud app
            cloud_base_url: Base URL of cloud app
            user_id: User ID for database updates
            
        Returns:
            True on success, False otherwise
        """
        try:
            from .registrar import WebhookRegistrar
            registrar = WebhookRegistrar(cloud_base_url, api_key)
            
            success, message = registrar.unregister()
            
            if success:
                self.app.logger.info(f"Webhook unregistered successfully: {message}")
                
                # update database
                try:
                    from models import Settings
                    settings = Settings.query.filter_by(user_id=user_id).first()
                    
                    if settings:
                        settings.cloud_webhook_url = None
                        self.db.session.commit()
                except Exception as db_error:
                    self.app.logger.error(f"Failed to update database after unregister: {str(db_error)}")
                
                return True
            else:
                self.app.logger.warning(f"Webhook unregister failed: {message}")
                return False
                
        except Exception:
            self.app.logger.error("Error unregistering webhook")
            return False
    
    def check_and_reregister_if_url_changed(self, user_id: int) -> bool:
        """
        Detect URL changes and trigger automatic re-registration.
        
        Compares stored tunnel URL with current tunnel URL.
        If they differ, triggers register_webhook() automatically.
        
        Args:
            user_id: User ID for database lookups and updates
            
        Returns:
            True if no change detected or re-registration succeeded, False otherwise
        """
        try:
            from models import Settings
            
            # get user settings
            settings = Settings.query.filter_by(user_id=user_id).first()
            
            if not settings:
                self.app.logger.error(f"Settings not found for user {user_id}")
                return False
            
            # check if tunnel is enabled
            if not settings.tunnel_enabled:
                self.app.logger.debug(f"Tunnel not enabled for user {user_id}, skipping URL check")
                return True
            
            # get stored tunnel URL
            stored_url = settings.tunnel_url
            
            if not stored_url:
                self.app.logger.debug(f"No stored tunnel URL for user {user_id}, skipping URL check")
                return True
            
            # get current tunnel URL (from process or config)
            # for now, we'll check if the process is running and the URL is still valid
            # in a real implementation, we might query cloudflared for the current URL
            current_url = self._get_current_tunnel_url(settings)
            
            if not current_url:
                self.app.logger.debug(f"Could not determine current tunnel URL for user {user_id}")
                return True
            
            # compare stored vs current URL
            if stored_url != current_url:
                self.app.logger.warning(
                    f"Tunnel URL changed for user {user_id}: {stored_url} -> {current_url}"
                )
                
                # update stored URL
                settings.tunnel_url = current_url
                self.db.session.commit()
                
                # trigger automatic re-registration
                if settings.cloud_enabled and settings.cloud_api_key and settings.cloud_base_url:
                    self.app.logger.info(f"Triggering automatic webhook re-registration for user {user_id}")
                    
                    webhook_secret = settings.cloud_webhook_secret or ''
                    
                    return self.register_webhook(
                        tunnel_url=current_url,
                        api_key=settings.cloud_api_key,
                        cloud_base_url=settings.cloud_base_url,
                        user_id=user_id,
                        webhook_secret=webhook_secret
                    )
                else:
                    self.app.logger.warning(
                        f"Cloud integration not configured for user {user_id}, "
                        "cannot re-register webhook"
                    )
                    return False
            
            # no URL change detected
            return True
            
        except Exception:
            self.app.logger.error("Error checking for URL changes")
            return False
    
    def _get_current_tunnel_url(self, settings) -> Optional[str]:
        """
        Get current tunnel URL from running process or config.
        
        Args:
            settings: User settings object
            
        Returns:
            Current tunnel URL or None if not available
        """
        # for now, we'll return the stored URL since cloudflared doesn't change URLs
        # for named tunnels (they're persistent)
        # in a real implementation, we might query cloudflared's API or parse logs
        
        # if process is running, assume the stored URL is current
        if self._is_process_running():
            return settings.tunnel_url
        
        # if process is not running, we can't determine the current URL
        return None
    
    def get_status(self, user_id: int) -> dict:
        """
        Return current tunnel status.
        
        Args:
            user_id: User ID to get status for
            
        Returns:
            Dict with status, url, last_error, etc.
        """
        try:
            from models import Settings
            settings = Settings.query.filter_by(user_id=user_id).first()
            
            if not settings:
                return {
                    'status': 'error',
                    'error': 'Settings not found'
                }
            
            # return current status from database
            return {
                'status': settings.tunnel_status or 'disconnected',
                'url': settings.tunnel_url,
                'last_error': settings.tunnel_last_error,
                'last_started': settings.tunnel_last_started.isoformat() if settings.tunnel_last_started else None,
                'enabled': settings.tunnel_enabled
            }
            
        except Exception:
            self.app.logger.error("Error getting tunnel status")
            return {
                'status': 'error',
                'error': "Failed to get tunnel status"
            }
    
    def reset_configuration(self, user_id: int) -> bool:
        """
        Clear all tunnel configuration and credentials.
        
        Args:
            user_id: User ID to reset configuration for
            
        Returns:
            True on success, False otherwise
        """
        try:
            # stop tunnel if running
            self.stop_tunnel(user_id)
            
            # clear database settings
            from models import Settings
            settings = Settings.query.filter_by(user_id=user_id).first()
            
            if settings:
                settings.tunnel_enabled = False
                settings.tunnel_url = None
                settings.tunnel_name = None
                settings.tunnel_credentials_encrypted = None
                settings.tunnel_status = 'disconnected'
                settings.tunnel_last_error = None
                settings.tunnel_last_started = None
                settings.tunnel_restart_count = 0
                settings.tunnel_last_health_check = None
                self.db.session.commit()
            
            self.app.logger.info(f"Reset tunnel configuration for user {user_id}")
            return True
            
        except Exception:
            self.app.logger.error("Failed to reset tunnel configuration")
            return False
    
    # internal methods (stubs for future implementation)
    
    def _detect_platform(self) -> str:
        """Detect OS and architecture."""
        pass
    
    def _get_binary_path(self) -> str:
        """Return path to cloudflared binary."""
        pass
    
    def _download_binary(self, platform: str) -> bool:
        """Download cloudflared binary."""
        pass
    
    def _verify_checksum(self, binary_path: str, expected_checksum: str) -> bool:
        """Verify binary integrity."""
        pass
    
    def _set_executable_permissions(self, binary_path: str) -> bool:
        """Set executable permissions on Unix."""
        pass
    
    def _run_auth_flow(self) -> Optional[dict]:
        """
        Execute cloudflared login flow.
        
        Opens browser for user authentication and waits for credentials.
        
        Returns:
            Credentials dict on success, None on failure
            
        Raises:
            AuthenticationError: If authentication fails
        """
        try:
            binary_path = self.binary_manager.get_binary_path()
            
            # run cloudflared login command
            # this opens the browser and waits for user to authenticate
            # credentials are saved to ~/.cloudflared/cert.pem by default
            process = subprocess.run(
                [binary_path, 'login'],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout for user to complete auth
            )
            
            if process.returncode != 0:
                error_msg = process.stderr.strip() if process.stderr else "Unknown error"
                raise AuthenticationError(f"cloudflared login failed: {error_msg}")
            
            # after successful login, credentials are stored in ~/.cloudflared/cert.pem
            # we need to read and parse this file
            import os
            cert_path = os.path.expanduser('~/.cloudflared/cert.pem')
            
            if not os.path.exists(cert_path):
                raise AuthenticationError("Credentials file not found after authentication")
            
            # read the cert file (it's actually a JSON file despite the .pem extension)
            with open(cert_path, 'r') as f:
                cert_content = f.read()
            
            # the cert.pem file contains the account credentials
            # we'll store the entire content as our credentials
            credentials = {
                'cert_content': cert_content,
                'cert_path': cert_path
            }
            
            return credentials
            
        except subprocess.TimeoutExpired:
            raise AuthenticationError("Authentication timed out after 5 minutes")
        except subprocess.SubprocessError:
            raise AuthenticationError("Failed to run cloudflared login")
        except OSError:
            raise AuthenticationError("Failed to read credentials file")
        except Exception:
            raise AuthenticationError("Unexpected error during authentication")
    
    def _encrypt_credentials(self, credentials: dict) -> str:
        """
        Encrypt credentials using AES-256-GCM.
        
        Args:
            credentials: Dictionary containing tunnel credentials
            
        Returns:
            Base64-encoded string containing nonce + ciphertext + tag
            
        Raises:
            ValueError: If SECRET_KEY is not configured
        """
        if not self.app.config.get('SECRET_KEY'):
            raise ValueError("Flask SECRET_KEY must be configured for credential encryption")
        
        # derive encryption key from Flask SECRET_KEY using PBKDF2
        encryption_key = self._derive_encryption_key()
        
        # serialize credentials to JSON
        plaintext = json.dumps(credentials).encode('utf-8')
        
        # generate random nonce (96 bits for GCM)
        nonce = os.urandom(12)
        
        # encrypt using AES-256-GCM (provides both confidentiality and integrity)
        aesgcm = AESGCM(encryption_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        
        # combine nonce + ciphertext and encode as base64
        # (ciphertext already includes the authentication tag from GCM)
        encrypted_data = nonce + ciphertext
        return b64encode(encrypted_data).decode('utf-8')
    
    def _decrypt_credentials(self, encrypted: str) -> Optional[dict]:
        """
        Decrypt credentials with integrity verification.
        
        Args:
            encrypted: Base64-encoded encrypted credentials
            
        Returns:
            Decrypted credentials dict on success, None on failure
        """
        try:
            if not self.app.config.get('SECRET_KEY'):
                raise ValueError("Flask SECRET_KEY must be configured for credential decryption")
            
            # derive encryption key from Flask SECRET_KEY
            encryption_key = self._derive_encryption_key()
            
            # decode from base64
            encrypted_data = b64decode(encrypted.encode('utf-8'))
            
            # extract nonce (first 12 bytes) and ciphertext (remaining bytes)
            nonce = encrypted_data[:12]
            ciphertext = encrypted_data[12:]
            
            # decrypt and verify integrity (GCM will raise exception if tampered)
            aesgcm = AESGCM(encryption_key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            
            # deserialize JSON
            credentials = json.loads(plaintext.decode('utf-8'))
            return credentials
        except Exception:
            # log the error but don't expose details
            self.app.logger.error("Failed to decrypt credentials")
            return None
    
    def _derive_encryption_key(self) -> bytes:
        """
        Derive encryption key from Flask SECRET_KEY using PBKDF2.
        
        Returns:
            32-byte encryption key suitable for AES-256
        """
        # use app-specific salt (not secret, just for key derivation)
        salt = b'seekandwatch-tunnel-credentials'
        
        # derive 256-bit key using PBKDF2-HMAC-SHA256
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,  # 256 bits for AES-256
            salt=salt,
            iterations=100000,  # OWASP recommended minimum
            backend=default_backend()
        )
        
        secret_key = self.app.config['SECRET_KEY'].encode('utf-8')
        return kdf.derive(secret_key)
    
    def _generate_tunnel_name(self, user_id: int) -> str:
        """
        Generate unique tunnel name.
        
        Pattern: seekandwatch-{user_id}-{random_suffix}
        
        Args:
            user_id: User ID for tunnel name
            
        Returns:
            Tunnel name string
        """
        import random
        import string
        
        # generate 8-character alphanumeric random suffix
        random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
        
        return f"seekandwatch-{user_id}-{random_suffix}"
    
    def _create_tunnel_config(self, tunnel_name: str, tunnel_url: str) -> dict:
        """
        Create tunnel configuration dict.
        
        Args:
            tunnel_name: Name of the tunnel
            tunnel_url: Public tunnel URL
            
        Returns:
            Configuration dict with ingress rules
        """
        # configure routing to /webhook endpoint only
        # all other paths get 404
        config = {
            'tunnel': tunnel_name,
            'ingress': [
                {
                    'hostname': tunnel_url.replace('https://', '').replace('http://', ''),
                    'service': 'http://127.0.0.1:5000',
                    'path': '/api/webhook'
                },
                {
                    'service': 'http_status:404'
                }
            ]
        }
        
        return config
    
    def _write_config_file(self, config: dict, tunnel_id: str) -> str:
        """
        Write tunnel config to file.
        
        Args:
            config: Configuration dict
            tunnel_id: Tunnel ID for filename
            
        Returns:
            Config file path
        """
        import yaml
        
        # ensure config directory exists
        os.makedirs(self.config_dir, exist_ok=True)
        
        # write config to YAML file
        config_path = os.path.join(self.config_dir, f'{tunnel_id}.yml')
        
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        
        self.app.logger.info(f"Wrote tunnel config to {config_path}")
        return config_path
    
    def _start_cloudflared_process(self, config_path: str) -> subprocess.Popen:
        """
        Start cloudflared subprocess.
        
        Spawns cloudflared as a subprocess with the given config file.
        Captures stdout and stderr for logging purposes.
        
        Args:
            config_path: Path to tunnel configuration YAML file
            
        Returns:
            Popen object for the running process
            
        Raises:
            ProcessManagementError: If process fails to start
        """
        try:
            binary_path = self.binary_manager.get_binary_path()
            
            if not os.path.exists(binary_path):
                raise ProcessManagementError(f"Cloudflared binary not found at {binary_path}")
            
            if not os.path.exists(config_path):
                raise ProcessManagementError(f"Config file not found at {config_path}")
            
            # prepare log file path for stdout/stderr
            log_path = os.path.join(self.config_dir, 'tunnel.log')
            
            # ensure config directory exists
            os.makedirs(self.config_dir, exist_ok=True)
            
            # open log file for writing (append mode)
            log_file = open(log_path, 'a')
            
            # start cloudflared tunnel run with config file
            # use Popen to run as background process
            process = subprocess.Popen(
                [binary_path, 'tunnel', '--config', config_path, 'run'],
                stdout=log_file,
                stderr=subprocess.STDOUT,  # redirect stderr to stdout (same log file)
                stdin=subprocess.DEVNULL,  # no stdin needed
                start_new_session=True  # detach from parent session
            )
            
            # give it a moment to start and check if it's still running
            import time
            time.sleep(1)
            
            if process.poll() is not None:
                # process exited immediately, something went wrong
                log_file.close()
                
                # read the last few lines of the log to get error details
                try:
                    with open(log_path, 'r') as f:
                        lines = f.readlines()
                        last_lines = ''.join(lines[-10:]) if len(lines) > 10 else ''.join(lines)
                except Exception:
                    last_lines = "Could not read log file"
                
                raise ProcessManagementError(
                    f"Cloudflared process exited immediately with code {process.returncode}. "
                    f"Last log lines: {last_lines}"
                )
            
            self.app.logger.info(f"Started cloudflared process (PID: {process.pid}), logging to {log_path}")
            
            # note: we keep log_file open so the process can continue writing to it
            # it will be closed when the process is terminated
            
            return process
            
        except ProcessManagementError:
            raise
        except Exception:
            raise ProcessManagementError("Failed to start cloudflared process")
    
    def _is_process_running(self) -> bool:
        """
        Check if cloudflared process is running.
        
        Uses psutil to check for actual running cloudflared processes,
        not just the subprocess reference (which doesn't persist across requests).
        
        Returns:
            True if process is running, False otherwise
        """
        import psutil
        
        # first check if we have a subprocess reference
        if self.process:
            # check if process has exited
            exit_code = self.process.poll()
            
            if exit_code is None:
                # process is still running
                return True
            
            # process has exited, log the details
            self._log_unexpected_exit(exit_code)
            
            # clean up the process reference
            self.process = None
        
        # check for any running cloudflared processes (in case subprocess reference was lost)
        try:
            for proc in psutil.process_iter(['name', 'cmdline']):
                try:
                    # check if this is a cloudflared process
                    if proc.info['name'] and 'cloudflared' in proc.info['name'].lower():
                        # found a cloudflared process
                        self.app.logger.debug(f"Found running cloudflared process: PID {proc.pid}")
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return False
        except Exception:
            self.app.logger.error("Error checking for cloudflared processes")
            return False
        
    
    def _log_unexpected_exit(self, exit_code: int):
        """
        Log unexpected process exit with details.
        
        Reads the last lines of stderr/stdout from the log file to provide context.
        
        Args:
            exit_code: Process exit code
        """
        try:
            log_path = os.path.join(self.config_dir, 'tunnel.log')
            
            # read last 20 lines of log file for context
            stderr_output = ""
            if os.path.exists(log_path):
                try:
                    with open(log_path, 'r') as f:
                        lines = f.readlines()
                        # grab last 20 lines
                        last_lines = lines[-20:] if len(lines) > 20 else lines
                        stderr_output = ''.join(last_lines)
                except Exception:
                    stderr_output = "Could not read log file"
                
            else:
                stderr_output = "Log file not found"
            
            # log the unexpected exit with context
            self.app.logger.error(
                f"Cloudflared process exited unexpectedly with code {exit_code}. "
                f"Last log output:\n{stderr_output}"
            )
            
            # also update database with error if possible
            try:
                from seekandwatch.models import Settings
                # find any settings with tunnel enabled
                settings_list = Settings.query.filter_by(tunnel_enabled=True).all()
                
                for settings in settings_list:
                    settings.tunnel_last_error = f"Process exited unexpectedly (code {exit_code})"
                    settings.tunnel_status = 'error'
                
                if settings_list:
                    self.db.session.commit()
            except Exception as db_error:
                self.app.logger.error(f"Failed to update database with exit error: {str(db_error)}")
                
        except Exception:
            self.app.logger.error("Error logging unexpected exit")
    
    def _terminate_process(self, timeout: int = 10) -> bool:
        """
        Terminate cloudflared process gracefully.
        
        Sends SIGTERM (or equivalent on Windows) and waits up to timeout seconds.
        If process doesn't exit gracefully, force-kills it.
        Uses psutil to find and kill cloudflared processes even without subprocess reference.
        
        Args:
            timeout: Maximum seconds to wait for graceful shutdown
            
        Returns:
            True if process exited gracefully, False if force-kill was needed
        """
        import psutil
        import signal
        import time
        
        killed_any = False
        
        # first try to terminate using subprocess reference if we have it
        if self.process:
            try:
                # check if process is still running
                if self.process.poll() is not None:
                    # process already exited
                    self.app.logger.info(f"Process already exited with code {self.process.returncode}")
                    self.process = None
                else:
                    # send SIGTERM for graceful shutdown (or CTRL_BREAK_EVENT on Windows)
                    try:
                        if os.name == 'nt':  # Windows
                            # on Windows, use CTRL_BREAK_EVENT
                            self.process.send_signal(signal.CTRL_BREAK_EVENT)
                        else:  # Unix-like (Linux, macOS)
                            self.process.terminate()  # sends SIGTERM
                        
                        self.app.logger.info(f"Sent termination signal to process {self.process.pid}")
                        killed_any = True
                    except Exception:
                        self.app.logger.warning("Failed to send termination signal")
                    
                    # wait up to timeout seconds for graceful exit
                    start_time = time.time()
                    while time.time() - start_time < timeout:
                        if self.process.poll() is not None:
                            # process exited gracefully
                            self.app.logger.info(
                                f"Process exited gracefully with code {self.process.returncode} "
                                f"after {time.time() - start_time:.1f} seconds"
                            )
                            self.process = None
                            break
                        
                        # wait a bit before checking again
                        time.sleep(0.5)
                    
                    # if still running after timeout, force-kill
                    if self.process and self.process.poll() is None:
                        self.app.logger.warning(
                            f"Process did not exit gracefully after {timeout} seconds, force-killing"
                        )
                        try:
                            self.process.kill()
                            self.process.wait(timeout=5)
                            self.app.logger.info("Process force-killed successfully")
                        except Exception:
                            self.app.logger.error("Failed to force-kill process")
                        finally:
                            self.process = None
            except Exception:
                self.app.logger.error("Error terminating subprocess")
                self.process = None
        
        # also check for any running cloudflared processes and kill them
        # (in case subprocess reference was lost)
        try:
            for proc in psutil.process_iter(['name', 'cmdline', 'pid']):
                try:
                    # check if this is a cloudflared process
                    if proc.info['name'] and 'cloudflared' in proc.info['name'].lower():
                        self.app.logger.info(f"Found cloudflared process (PID {proc.info['pid']}), terminating")
                        proc.terminate()
                        killed_any = True
                        
                        # wait for it to exit
                        try:
                            proc.wait(timeout=timeout)
                            self.app.logger.info(f"Cloudflared process {proc.info['pid']} terminated gracefully")
                        except psutil.TimeoutExpired:
                            self.app.logger.warning(f"Cloudflared process {proc.info['pid']} did not exit, force-killing")
                            proc.kill()
                            proc.wait(timeout=5)
                            self.app.logger.info(f"Cloudflared process {proc.info['pid']} force-killed")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            self.app.logger.error("Error killing cloudflared processes")
        
        return killed_any
    
    def create_tunnel_via_api(self, user_id: int, api_token: str, account_id: str = None) -> Optional[dict]:
        """
        Create Cloudflare tunnel using API (no browser needed).
        
        Args:
            user_id: User ID for database updates
            api_token: Cloudflare API token with tunnel permissions
            account_id: Cloudflare account ID (optional, will try to get from API)
            
        Returns:
            Dict with tunnel_id, token, and url on success, None on failure
        """
        import requests
        
        try:
            # if no account ID provided, get it from the API
            if not account_id:
                self.app.logger.info("Getting Cloudflare account ID from API")
                accounts_response = requests.get(
                    'https://api.cloudflare.com/client/v4/accounts',
                    headers={'Authorization': f'Bearer {api_token}'},
                    timeout=30
                )
                
                if accounts_response.status_code != 200:
                    self.app.logger.error(f"Failed to get accounts (HTTP {accounts_response.status_code}): {accounts_response.text}")
                    return None
                
                accounts_data = accounts_response.json()
                self.app.logger.debug(f"Accounts API response: {accounts_data}")
                
                if not accounts_data.get('success'):
                    errors = accounts_data.get('errors', [])
                    self.app.logger.error(f"Cloudflare API returned success=false: {errors}")
                    return None
                
                result = accounts_data.get('result', [])
                if not result or len(result) == 0:
                    self.app.logger.error("No accounts found in API response. Check that your API token has the correct permissions.")
                    return None
                
                account_id = result[0]['id']
                self.app.logger.info(f"Using account ID: {account_id}")
            
            # create tunnel via API
            tunnel_name = self._generate_tunnel_name(user_id)
            self.app.logger.info(f"Creating tunnel '{tunnel_name}' via Cloudflare API")
            
            create_response = requests.post(
                f'https://api.cloudflare.com/client/v4/accounts/{account_id}/cfd_tunnel',
                headers={
                    'Authorization': f'Bearer {api_token}',
                    'Content-Type': 'application/json'
                },
                json={
                    'name': tunnel_name,
                    'config_src': 'cloudflare'
                },
                timeout=30
            )
            
            if create_response.status_code != 200:
                self.app.logger.error(f"Failed to create tunnel (HTTP {create_response.status_code}): {create_response.text}")
                return None
            
            tunnel_data = create_response.json()
            if not tunnel_data.get('success') or not tunnel_data.get('result'):
                self.app.logger.error(f"Tunnel creation failed: {tunnel_data}")
                return None
            
            result = tunnel_data['result']
            tunnel_id = result['id']
            tunnel_token = result['token']
            tunnel_url = f"https://{tunnel_id}.cfargotunnel.com"
            
            self.app.logger.info(f"Tunnel created successfully: {tunnel_id}")
            
            # configure ingress rules via API (route all traffic to local app)
            # get the local URL to route to (defaults to 127.0.0.1:5000)
            local_url = os.environ.get('TUNNEL_LOCAL_URL', 'http://127.0.0.1:5000')
            
            self.app.logger.info(f"Configuring tunnel ingress to route to {local_url}")
            
            # ingress rules must always include a catch-all rule at the end
            # since we're using the default .cfargotunnel.com domain (no custom hostname),
            # we just route all traffic to the local service
            # originRequest settings tell cloudflared how to connect to the backend
            config_response = requests.put(
                f'https://api.cloudflare.com/client/v4/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations',
                headers={
                    'Authorization': f'Bearer {api_token}',
                    'Content-Type': 'application/json'
                },
                json={
                    'config': {
                        'ingress': [
                            {
                                'service': local_url,
                                'originRequest': {
                                    'noTLSVerify': True,
                                    'connectTimeout': 30
                                }
                            }
                        ]
                    }
                },
                timeout=30
            )
            
            if config_response.status_code not in [200, 201]:
                self.app.logger.warning(f"Failed to configure ingress (HTTP {config_response.status_code}): {config_response.text}")
                # don't fail the whole operation, tunnel can still work with default config
            else:
                self.app.logger.info("Tunnel ingress configured successfully")
            
            # store tunnel info in database
            from models import Settings
            settings = Settings.query.filter_by(user_id=user_id).first()
            
            if settings:
                settings.tunnel_name = tunnel_name
                settings.tunnel_url = tunnel_url
                settings.tunnel_status = 'created'
                # store the tunnel token encrypted
                settings.tunnel_credentials_encrypted = self._encrypt_credentials({
                    'tunnel_id': tunnel_id,
                    'tunnel_token': tunnel_token,
                    'account_id': account_id
                })
                self.db.session.commit()
            
            return {
                'tunnel_id': tunnel_id,
                'token': tunnel_token,
                'url': tunnel_url,
                'name': tunnel_name
            }
            
        except requests.RequestException:
            self.app.logger.error("API request failed")
            return None
        except Exception:
            self.app.logger.error("Unexpected error creating tunnel via API")
            return None
    
    def start_tunnel_with_token(self, user_id: int, tunnel_token: str) -> bool:
        """
        Start cloudflared using a tunnel token (no authentication needed).
        
        Ingress rules are configured via Cloudflare API, not command-line flags.
        
        Args:
            user_id: User ID for database updates
            tunnel_token: Tunnel token from Cloudflare API
            
        Returns:
            True on success, False otherwise
        """
        try:
            # prevent duplicate process instances
            if self._is_process_running():
                self.app.logger.warning("Cloudflared process already running")
                return True
            
            # ensure binary is available
            if not self.ensure_binary():
                self.app.logger.error("Cloudflared binary not available")
                return False
            
            binary_path = self.binary_manager.get_binary_path()
            
            # start cloudflared with the tunnel token
            # ingress rules are configured via API in create_tunnel_via_api()
            # don't use --url flag as it conflicts with API-configured tunnels
            self.app.logger.info(f"Starting cloudflared with tunnel token for user {user_id}")
            
            # prepare log file for cloudflared output
            log_dir = self.config_dir
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, 'tunnel.log')
            
            log_file = open(log_path, 'a')
            
            self.process = subprocess.Popen(
                [binary_path, 'tunnel', 'run', '--token', tunnel_token],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True
            )
            
            # give it a moment to start
            import time
            time.sleep(2)
            
            # check if process is still running
            if self.process.poll() is not None:
                # process exited immediately, something went wrong
                log_file.close()
                
                # read last lines of log for error details
                try:
                    with open(log_path, 'r') as f:
                        lines = f.readlines()
                        last_lines = ''.join(lines[-10:]) if len(lines) > 10 else ''.join(lines)
                except Exception:
                    last_lines = "Could not read log file"
                
                self.app.logger.error(f"Cloudflared exited immediately (code {self.process.returncode}): {last_lines}")
                return False
            
            # update database
            from models import Settings
            from datetime import datetime
            settings = Settings.query.filter_by(user_id=user_id).first()
            
            if settings:
                settings.tunnel_last_started = datetime.utcnow()
                settings.tunnel_status = 'connected'
                self.db.session.commit()
            
            self.app.logger.info(f"Cloudflared started successfully (PID: {self.process.pid}), logging to {log_path}")
            return True
            
        except Exception:
            self.app.logger.error("Failed to start tunnel with token")
            return False
    
    def _generate_tunnel_name(self, user_id: int) -> str:
        """Generate unique tunnel name for user."""
        import time
        timestamp = int(time.time())
        return f"seekandwatch-user{user_id}-{timestamp}"

    def start_quick_tunnel(self, user_id: int) -> Optional[str]:
        """
        Start a Cloudflare Quick Tunnel (trycloudflare.com).
        
        Does not require an account or API token.
        Parses output to find the assigned random URL.
        
        Args:
            user_id: User ID for database updates
            
        Returns:
            Tunnel URL on success, None on failure
        """
        import re
        import time
        
        try:
            # prevent duplicate process instances
            if self._is_process_running():
                self.app.logger.warning("Cloudflared process already running, stopping it first")
                self.stop_tunnel(user_id)
            
            # ensure binary is available
            if not self.ensure_binary():
                return None
            
            binary_path = self.binary_manager.get_binary_path()
            # Use 127.0.0.1 to ensure it hits the local server reliably
            local_url = os.environ.get('TUNNEL_LOCAL_URL', 'http://127.0.0.1:5000')
            
            self.app.logger.info(f"Starting Cloudflare Quick Tunnel for user {user_id} pointing to {local_url}")
            
            # prepare log file
            log_dir = self.config_dir
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, 'tunnel.log')
            
            # we need to capture output to find the URL
            # but we also want it to keep running in the background
            # so we'll start it, read from its pipe until we find the URL, then redirect to log
            
            process = subprocess.Popen(
                [binary_path, 'tunnel', '--url', local_url],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True
            )
            
            tunnel_url = None
            metrics_port = None
            start_time = time.time()
            timeout = 45  # 45 seconds to find the URL
            
            # regex patterns
            url_pattern = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com')
            metrics_pattern = re.compile(r'Metrics server listening on 127\.0\.0\.1:(\d+)')
            
            # read output line by line to find metrics port or URL
            with open(log_path, 'a') as log_file:
                log_file.write(f"\n--- Quick Tunnel Started at {time.ctime()} ---\n")
                
                while time.time() - start_time < timeout:
                    line = process.stdout.readline()
                    if not line:
                        break
                    
                    # Print to console for Docker log visibility during debugging
                    print(f"Cloudflare: {line.strip()}", flush=True)
                    
                    log_file.write(line)
                    log_file.flush()
                    
                    # 1. Try to find metrics port (more reliable)
                    metrics_match = metrics_pattern.search(line)
                    if metrics_match:
                        metrics_port = metrics_match.group(1)
                        self.app.logger.info(f"Found Cloudflare metrics port: {metrics_port}")
                        
                        # Query metrics endpoint for URL
                        try:
                            import requests
                            # Give cloudflared a second to establish connection
                            for _ in range(10):
                                time.sleep(1)
                                try:
                                    m_resp = requests.get(f"http://127.0.0.1:{metrics_port}/quicktunnelurl", timeout=2)
                                    if m_resp.status_code == 200:
                                        tunnel_url = m_resp.text.strip()
                                        if tunnel_url: break
                                except: continue
                        except Exception as me:
                            self.app.logger.warning(f"Metrics query failed: {me}")
                        
                        if tunnel_url: break

                    # 2. Fallback to stdout parsing
                    match = url_pattern.search(line)
                    if match:
                        tunnel_url = match.group(0)
                        self.app.logger.info(f"Found Quick Tunnel URL in stdout: {tunnel_url}")
                        break
                    
                    if process.poll() is not None:
                        break
            
            if not tunnel_url:
                self.app.logger.error("Failed to find Quick Tunnel URL in cloudflared output within timeout")
                process.terminate()
                return None
            
            # the process is still running and we have the URL
            self.process = process
            
            # update database
            from models import Settings
            from datetime import datetime
            settings = Settings.query.filter_by(user_id=user_id).first()
            
            if settings:
                settings.tunnel_url = tunnel_url
                settings.tunnel_name = 'quick-tunnel'
                settings.tunnel_last_started = datetime.utcnow()
                settings.tunnel_status = 'connected'
                settings.tunnel_enabled = True
                self.db.session.commit()
            
            # spawn a thread to keep reading output and writing to log so the pipe doesn't fill up
            def log_reader(proc, path):
                with open(path, 'a') as f:
                    for line in proc.stdout:
                        f.write(line)
                        f.flush()
            
            import threading
            threading.Thread(target=log_reader, args=(process, log_path), daemon=True).start()
            
            return tunnel_url
            
        except Exception:
            self.app.logger.error("Failed to start quick tunnel")
            return None
