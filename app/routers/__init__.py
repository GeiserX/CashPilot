"""Route groups extracted from app.main.

Only the low-regression ``auth``, ``pages``, and ``users`` groups live here.
Each handler references shared state (database, auth, catalog, templates, the
auth-guard deps) through the ``app.main`` namespace so that existing
``patch("app.main.*")`` test seams keep working after the split.
"""
