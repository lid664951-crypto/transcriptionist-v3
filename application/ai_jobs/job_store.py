"""
Job store helpers for AI tasks.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from transcriptionist_v3.infrastructure.database.models import Job, JobItem, AudioFile
from .job_constants import (
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_STATUS_PAUSED,
    JOB_STATUS_FAILED,
    JOB_STATUS_DONE,
    FILE_STATUS_PENDING,
    FILE_STATUS_DONE,
    FILE_STATUS_FAILED,
)


def create_job(
    session: Session,
    job_type: str,
    selection: dict | None,
    params: dict | None = None,
    total: int = 0,
) -> Job:
    job = Job(
        job_type=job_type,
        status=JOB_STATUS_PENDING,
        selection=selection,
        params=params,
        total=total,
        processed=0,
        failed=0,
        checkpoint=None,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def start_job(session: Session, job: Job, total: Optional[int] = None) -> None:
    job.status = JOB_STATUS_RUNNING
    job.started_at = job.started_at or datetime.utcnow()
    if total is not None:
        job.total = total
    session.commit()


def update_job_progress(
    session: Session,
    job: Job,
    processed: Optional[int] = None,
    failed: Optional[int] = None,
    total: Optional[int] = None,
    checkpoint: Optional[dict] = None,
) -> None:
    if processed is not None:
        job.processed = processed
    if failed is not None:
        job.failed = failed
    if total is not None:
        job.total = total
    if checkpoint is not None:
        job.checkpoint = checkpoint
    session.commit()


def finish_job(session: Session, job: Job, status: str, error: Optional[str] = None) -> None:
    job.status = status
    job.finished_at = datetime.utcnow()
    if error:
        job.error = error
    session.commit()


def ensure_job_items_for_paths(
    session: Session,
    job: Job,
    file_paths: Iterable[str],
) -> None:
    """为 files 模式创建 job_items（若已存在则跳过）。"""
    existing = session.query(JobItem.id).filter_by(job_id=job.id).first()
    if existing:
        return

    paths = [p for p in file_paths if p]
    if not paths:
        return

    BATCH = 500
    items = []
    for i in range(0, len(paths), BATCH):
        batch = paths[i : i + BATCH]
        normalized = set(batch)
        # 兼容 posix 路径
        for p in batch:
            if "\\" in p:
                normalized.add(p.replace("\\", "/"))
        rows = (
            session.query(AudioFile.id, AudioFile.file_path)
            .filter(AudioFile.file_path.in_(list(normalized)))
            .all()
        )
        path_to_id = {row.file_path: row.id for row in rows}
        for path in batch:
            audio_id = path_to_id.get(path)
            if audio_id is None and "\\" in path:
                audio_id = path_to_id.get(path.replace("\\", "/"))
            if audio_id is None:
                continue
            items.append(
                JobItem(
                    job_id=job.id,
                    audio_file_id=audio_id,
                    file_path=path,
                    status=FILE_STATUS_PENDING,
                )
            )
    if items:
        session.bulk_save_objects(items)
        session.commit()


def mark_job_paused(session: Session, job: Job) -> None:
    job.status = JOB_STATUS_PAUSED
    session.commit()


def mark_job_failed(session: Session, job: Job, error: str) -> None:
    job.status = JOB_STATUS_FAILED
    job.error = error
    job.finished_at = datetime.utcnow()
    session.commit()


def mark_job_done(session: Session, job: Job) -> None:
    job.status = JOB_STATUS_DONE
    job.finished_at = datetime.utcnow()
    session.commit()
