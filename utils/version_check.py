"""
python version check - critical safety feature

ensures the app is running on a compatible python version,
prevents cryptic errors from using unsupported syntax or features

this check runs on app startup before any imports that might fail
"""

import sys
import platform


# minimum required python version
MIN_PYTHON_VERSION = (3, 8, 0)
RECOMMENDED_PYTHON_VERSION = (3, 10, 0)


def check_python_version(min_version=MIN_PYTHON_VERSION, exit_on_fail=True):
    """
    check if current python version meets minimum requirements
    
    args:
        min_version: tuple of (major, minor, micro) version numbers
        exit_on_fail: if true, exit the program on version mismatch
        
    returns:
        bool: true if version is compatible, false otherwise
    """
    current_version = sys.version_info[:3]
    
    if current_version < min_version:
        error_msg = f"""
{'=' * 70}
PYTHON VERSION ERROR
{'=' * 70}

SeekAndWatch requires Python {'.'.join(map(str, min_version))} or higher.

Current Python version: {'.'.join(map(str, current_version))}
Python executable: {sys.executable}
Platform: {platform.platform()}

Please upgrade Python to continue.

Installation guides:
- Ubuntu/Debian: sudo apt-get install python3.10
- macOS: brew install python@3.10
- Windows: Download from https://www.python.org/downloads/
- Docker: Use python:3.10-slim base image

{'=' * 70}
"""
        print(error_msg, file=sys.stderr)
        
        if exit_on_fail:
            sys.exit(1)
        
        return False
    
    return True


def get_python_info():
    """
    grab detailed python version information
    
    returns:
        dict: python version details
    """
    return {
        'version': sys.version,
        'version_info': {
            'major': sys.version_info.major,
            'minor': sys.version_info.minor,
            'micro': sys.version_info.micro,
            'releaselevel': sys.version_info.releaselevel,
            'serial': sys.version_info.serial,
        },
        'executable': sys.executable,
        'platform': platform.platform(),
        'implementation': platform.python_implementation(),
        'compiler': platform.python_compiler(),
        'meets_minimum': sys.version_info[:3] >= MIN_PYTHON_VERSION,
        'meets_recommended': sys.version_info[:3] >= RECOMMENDED_PYTHON_VERSION,
    }


def print_python_info():
    """print python version information (for debugging)"""
    info = get_python_info()
    
    print("\n" + "=" * 70)
    print("PYTHON VERSION INFORMATION")
    print("=" * 70)
    print(f"Version: {info['version']}")
    print(f"Executable: {info['executable']}")
    print(f"Platform: {info['platform']}")
    print(f"Implementation: {info['implementation']}")
    print(f"Compiler: {info['compiler']}")
    print(f"\nMinimum required: {'.'.join(map(str, MIN_PYTHON_VERSION))}")
    print(f"Recommended: {'.'.join(map(str, RECOMMENDED_PYTHON_VERSION))}")
    print(f"\nMeets minimum: {'✅ Yes' if info['meets_minimum'] else '❌ No'}")
    print(f"Meets recommended: {'✅ Yes' if info['meets_recommended'] else '⚠️  No (still compatible)'}")
    print("=" * 70 + "\n")


def warn_if_old_version():
    """print a warning if python version is old but still compatible"""
    current_version = sys.version_info[:3]
    
    if MIN_PYTHON_VERSION <= current_version < RECOMMENDED_PYTHON_VERSION:
        print(f"""
⚠️  WARNING: You are using Python {'.'.join(map(str, current_version))}

While this version is supported, we recommend Python {'.'.join(map(str, RECOMMENDED_PYTHON_VERSION))} or higher
for better performance and security.

Your app will work fine, but consider upgrading when convenient.
""", file=sys.stderr)


# run check on import (before app starts)
if __name__ != '__main__':
    # only check on import, not when running as script
    check_python_version()
    warn_if_old_version()


if __name__ == '__main__':
    # when run as script, print detailed info
    print_python_info()

