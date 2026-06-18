# Ensure every ORM model is registered before the recipe uses the ORM directly (the recipe
# does not import app.main, so without this the Lead.assignee_id -> users FK can't resolve).
from app.models import audit, lead, settings, timeline, user  # noqa: F401
