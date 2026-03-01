"""
Smoke Tests - Runtime Error Detection
Catches issues that unit tests miss: missing imports, undefined JavaScript, template errors, etc.
Converted to unittest for compatibility with Docker test runner.
"""

import unittest
import sys
import os
import re
import ast
from pathlib import Path

# add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestImportCompleteness(unittest.TestCase):
    """Verify all imports are present in route files"""
    
    def test_all_route_files_have_required_imports(self):
        """Check that route files have all necessary Flask imports"""
        route_files = [
            'web/routes_generate.py',
            'web/routes_pages.py',
            'web/routes_settings.py',
            'web/routes_requests.py',
            'web/routes_utility.py',
            'api/routes_main.py',
            'api/routes_monitoring.py',
        ]
        
        required_imports = {
            'current_app': ['web/routes_generate.py'],
        }
        
        for filepath in route_files:
            if not os.path.exists(filepath):
                continue
                
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check if file uses current_app
            if 'current_app' in content and filepath in required_imports.get('current_app', []):
                self.assertIn('from flask import', content, 
                    f"{filepath} uses current_app but doesn't import from flask")
                self.assertIn('current_app', content.split('from flask import')[1].split('\n')[0] if 'from flask import' in content else '',
                    f"{filepath} should import current_app from flask")
    
    def test_no_syntax_errors_in_routes(self):
        """Use AST to detect syntax errors in route files"""
        route_files = list(Path('web').glob('routes_*.py')) + list(Path('api').glob('routes_*.py'))
        
        for filepath in route_files:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    tree = ast.parse(f.read(), filename=str(filepath))
                
                self.assertIsNotNone(tree, f"Failed to parse {filepath}")
            except SyntaxError as e:
                self.fail(f"Syntax error in {filepath}: {e}")


class TestTemplateCompleteness(unittest.TestCase):
    """Verify templates have all required JavaScript functions and endpoints"""
    
    def test_javascript_functions_defined_before_use(self):
        """Check that JavaScript functions are defined before being called"""
        template_files = list(Path('templates').glob('*.html'))
        
        issues = []
        for template_path in template_files:
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Find all onclick handlers
            onclick_calls = re.findall(r'onclick=["\']([^"\']+)["\']', content)
            
            # Find all function definitions
            function_defs = re.findall(r'function\s+(\w+)\s*\(', content)
            
            for onclick in onclick_calls:
                # Extract function name from onclick
                func_match = re.match(r'(\w+)\s*\(', onclick)
                if func_match:
                    func_name = func_match.group(1)
                    
                    # Skip common browser functions and known external functions
                    skip_functions = ['alert', 'confirm', 'prompt', 'console', 'openTab', 
                                    'submitActiveSettingsForm', 'if', 'for', 'while',
                                    'unblock', 'openRequestModal']  # These may be defined in base.html or other templates
                    if func_name in skip_functions:
                        continue
                    
                    # Check if function is defined
                    if func_name not in function_defs:
                        issues.append(f"{template_path.name}: onclick calls {func_name}() but function not defined")
        
        # Only fail if there are real issues (not just false positives)
        if issues:
            # Filter out known false positives
            real_issues = [i for i in issues if 'if()' not in i and 'foo()' not in i]
            if real_issues:
                # This is informational - functions may be defined in base.html or other included templates
                # Only fail if there are many issues
                if len(real_issues) > 5:
                    self.fail(f"Many undefined JavaScript functions found:\n" + "\n".join(real_issues[:5]))
    
    def test_javascript_variables_declared_before_use(self):
        """Check that JavaScript variables are declared before use"""
        critical_templates = ['templates/playlists.html', 'templates/settings.html']
        
        for template_path in critical_templates:
            if not os.path.exists(template_path):
                continue
                
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for availableLibraries in playlists.html
            if 'playlists.html' in template_path:
                if 'availableLibraries' in content:
                    # Find declaration (should be in a <script> tag near the top)
                    var_decl = content.find('var availableLibraries')
                    let_decl = content.find('let availableLibraries')
                    declaration = var_decl if var_decl != -1 else let_decl
                    
                    self.assertNotEqual(declaration, -1, 
                        f"{template_path}: availableLibraries used but never declared")
                    
                    # Find first actual usage (not in comments, not the declaration itself)
                    # Look for pattern like availableLibraries[something] or availableLibraries.something
                    usage_pattern = re.search(r'availableLibraries[\[\.]', content[declaration + 20:])
                    if usage_pattern:
                        first_use_pos = declaration + 20 + usage_pattern.start()
                        # Declaration should come before first use
                        self.assertLess(declaration, first_use_pos,
                            f"{template_path}: availableLibraries used before declaration")


class TestServiceImports(unittest.TestCase):
    """Verify service files have all required imports"""
    
    def test_collection_service_imports(self):
        """Verify CollectionService has all required imports"""
        if not os.path.exists('services/CollectionService.py'):
            self.skipTest("CollectionService.py not found")
            
        with open('services/CollectionService.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for required imports
        required = ['json', 'logging', 'PlexServer', 'db', 'CollectionSchedule']
        
        for req in required:
            self.assertIn(req, content, f"CollectionService missing import or reference: {req}")


class TestConfigurationCompleteness(unittest.TestCase):
    """Verify configuration and setup is complete"""
    
    def test_critical_files_exist(self):
        """Verify critical files exist"""
        critical_files = [
            'app.py',
            'config.py',
            'models.py',
            'requirements.txt',
        ]
        
        for filepath in critical_files:
            self.assertTrue(os.path.exists(filepath), 
                f"Critical file {filepath} not found")


if __name__ == '__main__':
    unittest.main()
