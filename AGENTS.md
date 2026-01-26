# Agent Best Practices & Anti-Patterns

This document outlines best practices and anti-patterns for AI agents working on this Python project.

## Python Best Practices

### Code Style
- **DO**: Follow PEP 8 style guidelines
- **DO**: Use type hints where appropriate
- **DO**: Keep functions focused and single-purpose
- **DON'T**: Use mutable default arguments (e.g., `def func(items=[])`)
- **DON'T**: Import `*` from modules (use explicit imports)

### Imports
- **DO**: Use absolute imports
- **DO**: Group imports: stdlib, third-party, local (with blank lines)
- **DO**: Keep imports at the top of the file
- **DON'T**: Use circular imports

### Error Handling
- **DO**: Use specific exception types
- **DO**: Provide meaningful error messages
- **DO**: Use context managers for resource management
- **DON'T**: Use bare `except:` clauses
- **DON'T**: Swallow exceptions silently

### Dependencies
- **DO**: Use `appdevcommons` for common utilities
- **DO**: Keep dependencies minimal and well-justified
- **DON'T**: Add dependencies without checking if `appdevcommons` provides similar functionality
- **DON'T**: Pin exact versions unless necessary (use `>=` for compatibility)

### Project Structure
- **DO**: Keep code in `src/balanceai/`
- **DO**: Use modules/packages for logical separation
- **DO**: Keep tests in `tests/` directory
- **DON'T**: Create unnecessary nested directories
- **DON'T**: Mix test code with production code

### Documentation
- **DO**: Write clear docstrings for public functions/classes
- **DO**: Update relevant `.md` files when making structural changes
- **DON'T**: Leave TODO comments without context
- **DON'T**: Document obvious code

## Anti-Patterns to Avoid

### Code Smells
- ❌ Long functions (>50 lines)
- ❌ Deep nesting (>3 levels)
- ❌ Duplicate code
- ❌ Magic numbers/strings (use constants)
- ❌ God classes/objects

### Testing
- ❌ Skipping tests
- ❌ Tests that depend on external services without mocking
- ❌ Tests without assertions
- ❌ Tests that test implementation details

### Git & Version Control
- ❌ Committing large binary files
- ❌ Committing `__pycache__/` or `.pyc` files
- ❌ Breaking changes without version bump
- ❌ Commit messages without context

## Project-Specific Guidelines

### Using appdevcommons
- Check `appdevcommons` documentation before implementing common utilities
- Prefer `appdevcommons` functions over custom implementations
- If `appdevcommons` doesn't have what you need, consider contributing or documenting why

### File Organization
- Keep related functionality together
- Use descriptive file and function names
- Follow existing patterns in the codebase

### Performance
- Don't optimize prematurely
- Use appropriate data structures
- Consider memory usage for large datasets

## When Making Changes

1. **Before coding**: Check if similar functionality exists
2. **During coding**: Follow style guidelines, write tests
3. **After coding**: Run linting, formatting, tests (see DEVELOPMENT.md)
4. **Before committing**: Update relevant documentation

## Constraints
