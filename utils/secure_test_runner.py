"""secure test execution with validation and sandboxing"""

import os
import sys
import subprocess
import hashlib
from pathlib import Path
from typing import Dict, Set, Optional
from utils.helpers import write_log

class SecureTestRunner:
    """handles secure test execution with comprehensive validation"""
    
    def __init__(self, tests_dir: str):
        self.tests_dir = Path(tests_dir).resolve()
        self.allowed_tests = self._scan_valid_tests()
        self.test_hashes = self._compute_test_hashes()
    
    def _scan_valid_tests(self) -> Set[str]:
        """scan tests directory for valid test files"""
        valid_tests = set()
        
        if not self.tests_dir.exists():
            return valid_tests
        
        for root, dirs, files in os.walk(self.tests_dir):
            # skip __pycache__ and hidden directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
            
            for file in files:
                if file.startswith('test_') and file.endswith('.py'):
                    rel_path = os.path.relpath(
                        os.path.join(root, file), 
                        self.tests_dir
                    )
                    valid_tests.add(rel_path)
        
        return valid_tests
    
    def _compute_test_hashes(self) -> Dict[str, str]:
        """compute sha256 hashes of test files for integrity checking"""
        hashes = {}
        for test_file in self.allowed_tests:
            full_path = self.tests_dir / test_file
            try:
                with open(full_path, 'rb') as f:
                    hashes[test_file] = hashlib.sha256(f.read()).hexdigest()
            except Exception:
                pass
        return hashes
    
    def verify_test_integrity(self, test_file: str) -> bool:
        """verify test file hasn't been tampered with"""
        if test_file not in self.test_hashes:
            return False
        
        full_path = self.tests_dir / test_file
        try:
            with open(full_path, 'rb') as f:
                current_hash = hashlib.sha256(f.read()).hexdigest()
            return current_hash == self.test_hashes[test_file]
        except Exception:
            return False
    
    def validate_test_file(self, test_file: str) -> tuple[bool, str]:
        """validate test file is safe to execute"""
        # check for path traversal
        if '..' in test_file or test_file.startswith('/') or test_file.startswith('\\'):
            return False, "path traversal detected"
        
        # check for absolute paths
        if os.path.isabs(test_file):
            return False, "absolute paths not allowed"
        
        # check whitelist
        if test_file not in self.allowed_tests:
            return False, f"test file not in whitelist: {test_file}"
        
        # verify file exists
        full_path = self.tests_dir / test_file
        if not full_path.exists():
            return False, "test file not found"
        
        # verify it's actually a file (not directory or symlink)
        if not full_path.is_file():
            return False, "not a regular file"
        
        if full_path.is_symlink():
            return False, "symlinks not allowed"
        
        # verify integrity
        if not self.verify_test_integrity(test_file):
            return False, "test file integrity check failed"
        
        return True, "ok"
    
    def run_test(self, test_file: str, timeout: int = 30) -> Dict:
        """safely execute a test file with validation and sandboxing"""
        # validate test file
        valid, message = self.validate_test_file(test_file)
        if not valid:
            write_log("error", "TestRunner", f"validation failed: {message} ({test_file})")
            return {
                'success': False,
                'error': message,
                'stdout': '',
                'stderr': '',
                'returncode': -1
            }
        
        full_path = self.tests_dir / test_file
        
        try:
            # run in isolated environment with resource limits
            result = subprocess.run(
                [sys.executable, '-m', 'pytest', str(full_path), '-v', '--tb=short'],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.tests_dir),
                env={
                    'PYTHONPATH': str(self.tests_dir),
                    'TESTING': '1',
                    'PYTEST_CURRENT_TEST': test_file
                }
            )
            
            # limit output size to prevent memory issues
            max_output = 10000  # 10k chars
            stdout = result.stdout[-max_output:] if len(result.stdout) > max_output else result.stdout
            stderr = result.stderr[-max_output:] if len(result.stderr) > max_output else result.stderr
            
            return {
                'success': result.returncode == 0,
                'stdout': stdout,
                'stderr': stderr,
                'returncode': result.returncode
            }
            
        except subprocess.TimeoutExpired:
            write_log("error", "TestRunner", f"test timed out: {test_file}")
            return {
                'success': False,
                'error': f'test timed out after {timeout} seconds',
                'stdout': '',
                'stderr': '',
                'returncode': -1
            }
        except Exception as e:
            write_log("error", "TestRunner", f"test execution failed: {str(e)}")
            return {
                'success': False,
                'error': f'execution failed: {str(e)}',
                'stdout': '',
                'stderr': '',
                'returncode': -1
            }
    
    def get_allowed_tests(self) -> list[str]:
        """get list of allowed test files"""
        return sorted(list(self.allowed_tests))
