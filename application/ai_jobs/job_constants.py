"""
Job constants for AI background tasks.
"""

# Job types
JOB_TYPE_INDEX = "index"
JOB_TYPE_TAG = "tag"
JOB_TYPE_TRANSLATE = "translate"
JOB_TYPE_CLEAR_TAGS = "clear_tags"
JOB_TYPE_APPLY_TRANSLATION = "apply_translation"

# Job status
JOB_STATUS_PENDING = "pending"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_PAUSED = "paused"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_DONE = "done"

# File status
FILE_STATUS_PENDING = 0
FILE_STATUS_DONE = 1
FILE_STATUS_FAILED = 2
