"""HTTP layer.

Routers only translate HTTP into service calls: validation lives in the
pydantic request models, business rules live in ``app.services`` and every
long-running action is handed to the task runner instead of blocking a
request.  Keeping this boundary thin is what lets the same services be used
from the workflow engine, the CLI scripts and the tests.
"""
