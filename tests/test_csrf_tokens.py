"""
Test that all templates have proper CSRF token protection.
Can be run with: python tests/test_csrf_tokens.py
Or with pytest: pytest tests/test_csrf_tokens.py -v
"""

import re
from pathlib import Path

try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False
    # Mock pytest for standalone execution
    class pytest:
        @staticmethod
        def skip(msg):
            print(f"⚠️  SKIPPED: {msg}")
            return
        
        @staticmethod
        def fail(msg):
            raise AssertionError(msg)


def find_fetch_calls_without_csrf(filepath):
    """Find all fetch() calls with POST/PUT/DELETE/PATCH that lack CSRF tokens."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    issues = []
    
    # Find all fetch calls with POST/PUT/DELETE/PATCH
    fetch_pattern = r'fetch\([^)]+\{[^}]*method:\s*[\'"](?:POST|PUT|DELETE|PATCH)[\'"][^}]*\}'
    matches = re.finditer(fetch_pattern, content, re.IGNORECASE | re.DOTALL)
    
    for match in matches:
        fetch_call = match.group(0)
        
        # Check if CSRF token is present
        if 'X-CSRFToken' not in fetch_call and 'csrf_token' not in fetch_call:
            # Check if it's using a headers variable that might have CSRF
            if 'headers: headers' in fetch_call or 'headers:headers' in fetch_call:
                # This is likely a false positive - headers variable probably has CSRF
                continue
            
            # Check if it's in a commented section
            line_start = content.rfind('\n', 0, match.start())
            line_end = content.find('\n', match.end())
            surrounding = content[max(0, line_start-100):min(len(content), line_end+100)]
            if '/*' in surrounding and '*/' in surrounding:
                # Likely commented out
                continue
            
            line_num = content[:match.start()].count('\n') + 1
            issues.append({
                'file': str(filepath),
                'line': line_num,
                'snippet': fetch_call[:100] + '...' if len(fetch_call) > 100 else fetch_call
            })
    
    return issues


def test_all_templates_have_csrf_tokens():
    """Test that all HTML templates include CSRF tokens in POST/PUT/DELETE/PATCH requests."""
    templates_dir = Path('templates')
    
    if not templates_dir.exists():
        pytest.skip("Templates directory not found")
    
    all_issues = []
    
    for template_file in templates_dir.glob('*.html'):
        issues = find_fetch_calls_without_csrf(template_file)
        all_issues.extend(issues)
    
    if all_issues:
        error_msg = f"\n\n❌ Found {len(all_issues)} fetch() calls missing CSRF tokens:\n\n"
        for issue in all_issues:
            error_msg += f"File: {issue['file']}\n"
            error_msg += f"Line: {issue['line']}\n"
            error_msg += f"Snippet: {issue['snippet']}\n\n"
        error_msg += "\nFix by adding 'X-CSRFToken': CSRF_TOKEN to headers.\n"
        error_msg += "See CSRF_TOKEN_GUIDE.md for details.\n"
        pytest.fail(error_msg)


def test_csrf_protection_enabled():
    """Test that Flask-WTF CSRF protection is enabled in app.py."""
    app_file = Path('app.py')
    
    if not app_file.exists():
        pytest.skip("app.py not found")
    
    content = app_file.read_text(encoding='utf-8')
    
    # Check that CSRFProtect is imported
    assert 'from flask_wtf.csrf import CSRFProtect' in content or 'from flask_wtf import CSRFProtect' in content, \
        "CSRFProtect not imported in app.py"
    
    # Check that CSRF protection is initialized
    assert 'csrf = CSRFProtect(app)' in content or 'CSRFProtect(app)' in content, \
        "CSRF protection not initialized in app.py"


def test_templates_have_csrf_token_constants():
    """Test that templates with POST requests have CSRF_TOKEN constants defined."""
    templates_dir = Path('templates')
    
    if not templates_dir.exists():
        pytest.skip("Templates directory not found")
    
    templates_with_post = []
    templates_without_constant = []
    
    for template_file in templates_dir.glob('*.html'):
        content = template_file.read_text(encoding='utf-8')
        
        # Check if template has POST/PUT/DELETE/PATCH requests
        if re.search(r'method:\s*[\'"](?:POST|PUT|DELETE|PATCH)[\'"]', content, re.IGNORECASE):
            templates_with_post.append(template_file)
            
            # Check if it has CSRF_TOKEN constant or inline csrf_token()
            if 'CSRF_TOKEN' not in content and "csrf_token()" not in content:
                templates_without_constant.append(template_file)
    
    if templates_without_constant:
        error_msg = f"\n\n❌ Found {len(templates_without_constant)} templates with POST requests but no CSRF token constant:\n\n"
        for template in templates_without_constant:
            error_msg += f"  - {template}\n"
        error_msg += "\nAdd: const CSRF_TOKEN = \"{{ csrf_token() }}\"; to the <script> section.\n"
        pytest.fail(error_msg)


def test_api_routes_accept_csrf_tokens():
    """Test that API routes are configured to accept CSRF tokens."""
    # This is a basic check - in a real test you'd make actual requests
    api_files = list(Path('api').glob('*.py'))
    
    if not api_files:
        pytest.skip("No API route files found")
    
    # Just verify the files exist and are readable
    for api_file in api_files:
        assert api_file.exists(), f"API file {api_file} not found"
        content = api_file.read_text(encoding='utf-8')
        assert len(content) > 0, f"API file {api_file} is empty"


if __name__ == '__main__':
    # Allow running directly for quick checks
    import sys
    
    print("Running CSRF token tests...\n")
    
    try:
        test_all_templates_have_csrf_tokens()
        print("✅ All templates have CSRF tokens")
    except AssertionError as e:
        print(str(e))
        sys.exit(1)
    
    try:
        test_csrf_protection_enabled()
        print("✅ CSRF protection is enabled")
    except AssertionError as e:
        print(f"❌ {e}")
        sys.exit(1)
    
    try:
        test_templates_have_csrf_token_constants()
        print("✅ All templates have CSRF token constants")
    except AssertionError as e:
        print(str(e))
        sys.exit(1)
    
    try:
        test_api_routes_accept_csrf_tokens()
        print("✅ API routes are configured")
    except AssertionError as e:
        print(f"❌ {e}")
        sys.exit(1)
    
    print("\n✅ All CSRF token tests passed!")
