"""Playwright-backed browser package.

The `manager` module owns the single, lazy-started Chromium context that
Phase 2's browser tools drive. Import it, don't touch Playwright directly
from tool code.
"""
