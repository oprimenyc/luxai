"""
Trade Idea Workbench — orchestration package.

Path: apps/api/src/workbench/__init__.py
Security: No credentials. Orchestrates options chain fetch, Greeks, scoring,
          recommendation, and calendar — all pure logic or delegated to
          services that hold their own credentials.
Scale: Each analyze() call is a single request pipeline; no shared state.
"""
