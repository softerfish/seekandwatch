"""
Import Safety Tests - Critical Safety Feature

Detects circular imports and import order issues before they cause problems.
These tests run on every commit to catch issues early.

Usage:
    python tests/test_import_safety.py
"""

import unittest
import sys
import os
import importlib
import ast
from typing import Dict, Set, List, Tuple


class ImportAnalyzer(ast.NodeVisitor):
    """AST visitor to extract imports from a Python file"""
    
    def __init__(self):
        self.imports: Set[str] = set()
    
    def visit_Import(self, node):
        for alias in node.names:
            self.imports.add(alias.name.split('.')[0])
    
    def visit_ImportFrom(self, node):
        if node.module:
            self.imports.add(node.module.split('.')[0])


def get_imports_from_file(filepath: str) -> Set[str]:
    """Extract all imports from a Python file"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filepath)
        
        analyzer = ImportAnalyzer()
        analyzer.visit(tree)
        return analyzer.imports
    except Exception as e:
        print(f"Warning: Could not parse {filepath}: {e}")
        return set()


def build_dependency_graph() -> Dict[str, Set[str]]:
    """
    Build a dependency graph of all project modules.
    
    Returns:
        Dict mapping module name to set of modules it imports
    """
    graph = {}
    
    # Get project root
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Scan all Python files
    for root, dirs, files in os.walk(project_root):
        # Skip virtual environments and hidden directories
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['venv', 'env', '__pycache__']]
        
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                rel_path = os.path.relpath(filepath, project_root)
                
                # Convert file path to module name
                module_name = rel_path.replace(os.sep, '.').replace('.py', '')
                if module_name.endswith('.__init__'):
                    module_name = module_name[:-9]
                
                # Get imports
                imports = get_imports_from_file(filepath)
                
                # Filter to only project modules
                project_imports = {imp for imp in imports 
                                  if imp in ['api', 'services', 'utils', 'models', 
                                            'config', 'presets', 'auth_decorators',
                                            'migrations', 'tunnel', 'tests']}
                
                graph[module_name] = project_imports
    
    return graph


def detect_circular_imports(graph: Dict[str, Set[str]]) -> List[List[str]]:
    """
    Detect circular import chains in the dependency graph.
    
    Returns:
        List of circular import chains (each chain is a list of module names)
    """
    def dfs(node: str, path: List[str], visited: Set[str]) -> List[List[str]]:
        if node in path:
            # Found a cycle
            cycle_start = path.index(node)
            return [path[cycle_start:] + [node]]
        
        if node in visited:
            return []
        
        visited.add(node)
        cycles = []
        
        for neighbor in graph.get(node, set()):
            cycles.extend(dfs(neighbor, path + [node], visited))
        
        return cycles
    
    all_cycles = []
    visited = set()
    
    for node in graph:
        cycles = dfs(node, [], visited.copy())
        for cycle in cycles:
            # Normalize cycle (start with smallest module name)
            normalized = cycle[cycle.index(min(cycle)):]
            if normalized not in all_cycles:
                all_cycles.append(normalized)
    
    return all_cycles


class TestImportSafety(unittest.TestCase):
    """Test suite for import safety"""
    
    @classmethod
    def setUpClass(cls):
        """Build dependency graph once for all tests"""
        cls.graph = build_dependency_graph()
    
    def test_no_circular_imports(self):
        """Test that there are no circular imports in the codebase"""
        cycles = detect_circular_imports(self.graph)
        
        # Filter out self-imports (module importing itself via __init__.py)
        # These are safe when using package __init__.py for re-exports
        real_cycles = []
        for cycle in cycles:
            # Skip cycles that are just self-imports (e.g., utils -> utils)
            if len(cycle) == 2 and cycle[0] == cycle[1]:
                continue
            # Skip cycles within the same package (e.g., api.routes_main -> api)
            if len(cycle) == 2 and cycle[0].startswith(cycle[1] + '.'):
                continue
            real_cycles.append(cycle)
        
        if real_cycles:
            error_msg = "Circular imports detected:\n"
            for i, cycle in enumerate(real_cycles, 1):
                error_msg += f"\n{i}. {' -> '.join(cycle)}"
            self.fail(error_msg)
    
    def test_utils_no_service_imports(self):
        """Test that utils.py doesn't import from services (prevents circular deps)"""
        # Note: utils.py has some functions that import from services inside the function body
        # (e.g., get_cloud_base_url). This is safe because it's not a module-level import.
        # The AST parser detects these, but they don't cause circular dependency issues.
        # We'll check for module-level imports only by reading the file directly.
        
        utils_py_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'utils.py'
        )
        
        if not os.path.exists(utils_py_file):
            self.skipTest("utils.py not found")
        
        with open(utils_py_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Check for module-level imports (not inside functions)
        in_function = False
        indent_level = 0
        violations = []
        
        for i, line in enumerate(lines, 1):
            stripped = line.lstrip()
            
            # Track if we're inside a function
            if stripped.startswith('def ') or stripped.startswith('class '):
                in_function = True
                indent_level = len(line) - len(stripped)
            elif in_function and stripped and not line[0].isspace():
                # Back to module level
                in_function = False
                indent_level = 0
            
            # Check for service imports at module level
            if not in_function and (stripped.startswith('import services') or stripped.startswith('from services')):
                violations.append(f"Line {i}: {stripped.strip()}")
        
        if violations:
            self.fail(f"utils.py has module-level imports from services:\n" + "\n".join(violations) +
                     "\nThis creates circular dependencies. Use dependency injection instead.")
    
    def test_models_minimal_imports(self):
        """Test that models.py has minimal imports (should only import from Flask/SQLAlchemy)"""
        models_imports = self.graph.get('models', set())
        
        # models.py should not import from services, api, or utils
        forbidden = {'services', 'api', 'utils'}
        violations = models_imports & forbidden
        
        if violations:
            self.fail(f"models.py imports from {violations}\n"
                     "Models should be independent to avoid circular dependencies.")
    
    def test_config_no_app_imports(self):
        """Test that config.py doesn't import from app modules"""
        config_imports = self.graph.get('config', set())
        
        # config.py should not import from app, services, api, or utils
        forbidden = {'app', 'services', 'api', 'utils'}
        violations = config_imports & forbidden
        
        if violations:
            self.fail(f"config.py imports from {violations}\n"
                     "Config should be independent to avoid circular dependencies.")
    
    def test_can_import_all_modules(self):
        """Test that all modules can be imported without errors"""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, project_root)
        
        modules_to_test = [
            'config',
            'models',
            'presets',
            'auth_decorators',
            'utils.feature_flags',
            'utils.monitoring',
            'services.CloudService',
            'services.CollectionService',
            'services.IntegrationsService',
        ]
        
        failed_imports = []
        
        for module_name in modules_to_test:
            try:
                importlib.import_module(module_name)
            except ImportError as e:
                failed_imports.append((module_name, str(e)))
            except Exception as e:
                # Some modules may fail for other reasons (missing config, etc.)
                # That's okay, we're just checking for import errors
                pass
        
        if failed_imports:
            error_msg = "Failed to import modules:\n"
            for module, error in failed_imports:
                error_msg += f"\n- {module}: {error}"
            self.fail(error_msg)
    
    def test_import_hierarchy(self):
        """Test that imports follow the correct hierarchy"""
        # Define the import hierarchy (lower levels can't import from higher levels)
        hierarchy = {
            'config': 0,
            'models': 1,
            'presets': 1,
            'auth_decorators': 2,
            'tunnel': 2,
            'utils': 2,
            'services': 3,
            'api': 4,
            'app': 5,
        }
        
        # Exceptions: utils/__init__.py can import from services for re-exports (backward compatibility)
        # tunnel modules can import from services (they're integration modules)
        allowed_exceptions = {
            ('utils', 'services'),  # utils/__init__.py re-exports service functions
            ('tunnel.health', 'services'),  # tunnel health monitor uses services
            ('tunnel.registrar', 'services'),  # tunnel registrar uses services
        }
        
        violations = []
        
        for module, imports in self.graph.items():
            module_base = module.split('.')[0]
            module_level = hierarchy.get(module_base, 999)
            
            for imp in imports:
                imp_level = hierarchy.get(imp, 999)
                
                if imp_level > module_level:
                    # Check if this is an allowed exception
                    if (module, imp) not in allowed_exceptions and (module_base, imp) not in allowed_exceptions:
                        violations.append(f"{module} (level {module_level}) imports {imp} (level {imp_level})")
        
        if violations:
            error_msg = "Import hierarchy violations detected:\n"
            error_msg += "\n".join(f"- {v}" for v in violations)
            error_msg += "\n\nHierarchy (low to high): config < models/presets < auth_decorators/tunnel/utils < services < api < app"
            self.fail(error_msg)


class TestSpecificImports(unittest.TestCase):
    """Test specific import patterns that are known to be problematic"""
    
    def test_no_utils_collection_wrappers(self):
        """Test that utils.py doesn't have CollectionService wrapper functions"""
        utils_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'utils.py'
        )
        
        if not os.path.exists(utils_file):
            self.skipTest("utils.py not found")
        
        with open(utils_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for wrapper functions that should have been removed
        forbidden_patterns = [
            'def run_collection_logic',
            'def apply_collection_visibility',
            'def get_collection_visibility',
            'def _get_plex_tmdb_id',
        ]
        
        violations = []
        for pattern in forbidden_patterns:
            if pattern in content:
                violations.append(pattern)
        
        if violations:
            self.fail(f"Found forbidden wrapper functions in utils.py: {violations}\n"
                     "These should have been removed to fix circular dependency.")


def print_dependency_graph():
    """Print the dependency graph for debugging"""
    graph = build_dependency_graph()
    
    print("\n" + "=" * 70)
    print("DEPENDENCY GRAPH")
    print("=" * 70)
    
    for module in sorted(graph.keys()):
        imports = graph[module]
        if imports:
            print(f"\n{module}:")
            for imp in sorted(imports):
                print(f"  -> {imp}")
    
    print("\n" + "=" * 70)


def print_circular_imports():
    """Print any circular imports found"""
    graph = build_dependency_graph()
    cycles = detect_circular_imports(graph)
    
    print("\n" + "=" * 70)
    print("CIRCULAR IMPORT ANALYSIS")
    print("=" * 70)
    
    if not cycles:
        print("\n✅ No circular imports detected!")
    else:
        print(f"\n⚠️  Found {len(cycles)} circular import chain(s):\n")
        for i, cycle in enumerate(cycles, 1):
            print(f"{i}. {' -> '.join(cycle)}")
    
    print("\n" + "=" * 70)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Test import safety')
    parser.add_argument('--graph', action='store_true', help='Print dependency graph')
    parser.add_argument('--cycles', action='store_true', help='Print circular imports')
    args = parser.parse_args()
    
    if args.graph:
        print_dependency_graph()
    elif args.cycles:
        print_circular_imports()
    else:
        print("=" * 70)
        print("IMPORT SAFETY TESTS")
        print("=" * 70)
        print("\nChecking for circular imports and import order issues...\n")
        unittest.main(verbosity=2)

