"""
Cloudflared binary management - download, verification, and updates.
"""

import os
import platform
import hashlib
import stat
import requests
from pathlib import Path
from typing import Optional
from .exceptions import BinaryDownloadError


class BinaryManager:
    """Manages cloudflared binary download, verification, and updates."""
    
    CLOUDFLARE_DOWNLOAD_BASE = "https://github.com/cloudflare/cloudflared/releases/download"
    
    def __init__(self, config_dir: str):
        """
        Initialize binary manager.
        
        Args:
            config_dir: Directory path for storing cloudflared binary and config
        """
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
    
    def ensure_binary(self) -> bool:
        """
        Ensure cloudflared binary exists and is valid.

        Checks for existing binary and downloads if missing.
        Handles download failures with error logging.

        Returns:
            True if binary is ready, False otherwise
        """
        binary_path = self._get_binary_path()

        # check if binary already exists
        if os.path.exists(binary_path):
            # verify it's executable on Unix systems
            if platform.system().lower() != 'windows':
                try:
                    # check if file has execute permission
                    if not os.access(binary_path, os.X_OK):
                        # try to set executable permissions
                        self._set_executable_permissions(binary_path)
                except BinaryDownloadError:
                    # log error but continue - might still work
                    print("Warning: Failed to set executable permissions for existing binary")

            return True

        # binary doesn't exist, need to download
        try:
            # detect platform
            platform_str = self._detect_platform()

            # download binary
            self._download_binary(platform_str)

            # set executable permissions on Unix
            self._set_executable_permissions(binary_path)

            return True

        except BinaryDownloadError:
            # log the error with context
            print("Error downloading cloudflared binary")
            return False

    
    def check_for_updates(self) -> Optional[str]:
        """
        Check for newer cloudflared version.
        
        Returns:
            New version string if available, None otherwise
        """
        # stub - will be implemented in task 4
        pass
    
    def update_binary(self) -> bool:
        """
        Download and install newer version.
        
        Returns:
            True on success, False otherwise
        """
        # stub - will be implemented in task 4
        pass
    
    def get_binary_path(self) -> str:
        """
        Return path to cloudflared binary.
        
        Returns:
            Absolute path to binary
        """
        return self._get_binary_path()
    
    def get_current_version(self) -> Optional[str]:
        """
        Return currently installed version string.
        
        Returns:
            Version string or None if not installed
        """
        # stub - will be implemented in task 4
        pass
    
    def _detect_platform(self) -> str:
        """
        Detect OS and architecture.

        Returns:
            Platform string (e.g., 'linux-amd64', 'windows-amd64', 'darwin-amd64')
        """
        system = platform.system().lower()
        machine = platform.machine().lower()

        # map OS names
        os_map = {
            'linux': 'linux',
            'darwin': 'darwin',
            'windows': 'windows'
        }

        # map architecture names
        arch_map = {
            'x86_64': 'amd64',
            'amd64': 'amd64',
            'aarch64': 'arm64',
            'arm64': 'arm64',
            'armv7l': 'arm'
        }

        os_name = os_map.get(system)
        arch_name = arch_map.get(machine)

        if not os_name or not arch_name:
            raise BinaryDownloadError(
                f"Unsupported platform: {system} {machine}"
            )

        return f"{os_name}-{arch_name}"

    
    def _get_binary_path(self) -> str:
        """
        Return path to cloudflared binary in config directory.
        
        Returns:
            Absolute path to binary
        """
        binary_name = "cloudflared"
        
        # add .exe extension on Windows
        if platform.system().lower() == 'windows':
            binary_name += ".exe"
        
        return str(self.config_dir / binary_name)
    
    def _download_binary(self, platform_str: str, version: str = "2024.12.2") -> bool:
        """
        Download cloudflared binary for platform.
        
        Args:
            platform_str: Platform string (e.g., 'linux-amd64')
            version: Version to download (default: known stable version)
            
        Returns:
            True on success, False otherwise
            
        Raises:
            BinaryDownloadError: If download fails
        """
        try:
            # construct download URL
            # github releases use the pattern: /releases/download/{version}/cloudflared-{platform}
            # we use a known stable version by default instead of "latest" which doesn't work
            url = f"{self.CLOUDFLARE_DOWNLOAD_BASE}/{version}/cloudflared-{platform_str}"
            
            binary_path = self._get_binary_path()
            
            # download binary with redirect following
            response = requests.get(url, stream=True, timeout=300, allow_redirects=True)
            response.raise_for_status()
            
            # write to temp file first, then rename (atomic operation)
            temp_path = f"{binary_path}.tmp"
            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            # rename temp file to final location
            os.replace(temp_path, binary_path)
            
            return True
            
        except requests.RequestException as e:
            # clean up temp file if it exists
            temp_path = f"{binary_path}.tmp"
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise BinaryDownloadError(
                "Failed to download cloudflared binary"
            )
        except OSError:
            raise BinaryDownloadError(
                "Failed to write cloudflared binary"
            )
    
    def _verify_checksum(self, binary_path: str, expected_checksum: str) -> bool:
        """
        Verify binary integrity using SHA256 checksum.
        
        Args:
            binary_path: Path to binary file
            expected_checksum: Expected SHA256 checksum (hex string)
            
        Returns:
            True if checksum matches, False otherwise
        """
        try:
            sha256_hash = hashlib.sha256()
            
            with open(binary_path, 'rb') as f:
                # read in chunks to handle large files
                for chunk in iter(lambda: f.read(8192), b''):
                    sha256_hash.update(chunk)
            
            actual_checksum = sha256_hash.hexdigest()
            
            # case-insensitive comparison
            return actual_checksum.lower() == expected_checksum.lower()
            
        except OSError:
            raise BinaryDownloadError(
                "Failed to read binary for checksum verification"
            )
    
    def _set_executable_permissions(self, binary_path: str) -> bool:
        """
        Set executable permissions on Unix systems (Linux, macOS).
        
        Args:
            binary_path: Path to binary file
            
        Returns:
            True on success, False otherwise
            
        Raises:
            BinaryDownloadError: If setting permissions fails
        """
        # only set permissions on Unix systems
        if platform.system().lower() == 'windows':
            return True  # Windows doesn't need chmod
        
        try:
            # set executable permissions (chmod +x)
            # stat.S_IXUSR = owner execute, stat.S_IRUSR = owner read, stat.S_IWUSR = owner write
            current_permissions = os.stat(binary_path).st_mode
            new_permissions = current_permissions | stat.S_IXUSR | stat.S_IRUSR | stat.S_IWUSR
            os.chmod(binary_path, new_permissions)
            return True
            
        except OSError:
            raise BinaryDownloadError(
                "Failed to set executable permissions"
            )
