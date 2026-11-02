"""Application services.

Layering rule: routers → services → agents/providers → models.  Services own
transactions and workflow state; agents never touch the database directly.
Submodules are imported explicitly by callers to keep import graphs acyclic.
"""
