"""Workspaces bounded context: repository ingestion, workspace lifecycle,
guarded filesystem access, and git operations.

The security heart of this context is :class:`SafeFileSystem` — every file
access in the platform flows through it, and it is the only sanctioned path to
a workspace's contents (SEC-FS).
"""
