# Path: apps/api/src/data/__init__.py
# Security: No credentials stored here. Each client reads from env on init.
# Scale: Clients are stateless wrappers; cache lives in Redis, not in-process.
