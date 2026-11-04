"""SubmissionStore: one JSON object per submission.

Key scheme (identical for both backends):
    submissions/<YYYY>/<MM>/<submission_id>.json

``S3SubmissionStore`` is the deployed backend (Amazon S3 is the only
persistent store). ``LocalSubmissionStore`` mirrors the same keys on disk so
the app runs offline in the hackathon sandbox or on a laptop.
"""
from __future__ import annotations

import json
import re
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Protocol


@dataclass
class SubmissionRecord:
    submission_id: str
    timestamp: str
    profile: dict
    category: str
    in_scope_domains: list
    answers: dict
    scores: dict
    gaps: list
    research_summary: str | None = None
    recommendations: list = field(default_factory=list)
    action_plan: list = field(default_factory=list)
    overview: str | None = None
    orchestration_status: str = "pending"
    orchestration_error: str | None = None
    synthetic: bool = False
    # Narrative-only additions; scores, stages and gaps above never change after scoring.
    domain_analysis: dict = field(default_factory=dict)      # domain_id -> analysis paragraph
    org_context: list = field(default_factory=list)          # [{text, timestamp}] the org added later
    revision_status: str = "none"                            # none | pending | ok | error
    revision_error: str | None = None
    revision_count: int = 0
    revisions: list = field(default_factory=list)            # earlier narrative versions, newest last

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SubmissionRecord":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


def slugify(value: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug[:max_len].rstrip("-")) or "org"


def new_submission_id(org_name: str, now: datetime | None = None) -> str:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H-%M-%SZ")
    return "%s_%s_%s" % (stamp, slugify(org_name), secrets.token_hex(3))


_ID_RE = re.compile(r"^(\d{4})-(\d{2})-\d{2}T\d{2}-\d{2}-\d{2}Z_[a-z0-9-]+_[0-9a-f]{6}$")


def key_for(submission_id: str) -> str:
    m = _ID_RE.match(submission_id)
    if not m:
        raise ValueError("invalid submission id")
    return "submissions/%s/%s/%s.json" % (m.group(1), m.group(2), submission_id)


class SubmissionStore(Protocol):
    def put(self, record: SubmissionRecord) -> str: ...
    def get(self, submission_id: str) -> SubmissionRecord | None: ...
    def list_records(self, prefixes: Iterable[str] | None = None) -> list[SubmissionRecord]: ...
    def is_empty(self) -> bool: ...


class LocalSubmissionStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def put(self, record: SubmissionRecord) -> str:
        key = key_for(record.submission_id)
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record.to_dict(), indent=2))
        tmp.replace(path)
        return key

    def get(self, submission_id: str) -> SubmissionRecord | None:
        path = self.root / key_for(submission_id)
        if not path.exists():
            return None
        return SubmissionRecord.from_dict(json.loads(path.read_text()))

    def list_records(self, prefixes: Iterable[str] | None = None) -> list[SubmissionRecord]:
        base = self.root / "submissions"
        if not base.exists():
            return []
        paths = []
        for prefix in (prefixes or ["submissions/"]):
            p = self.root / prefix
            if p.is_dir():
                paths.extend(p.rglob("*.json"))
        return [SubmissionRecord.from_dict(json.loads(x.read_text())) for x in sorted(set(paths))]

    def is_empty(self) -> bool:
        base = self.root / "submissions"
        return not base.exists() or not any(base.rglob("*.json"))


class S3SubmissionStore:
    def __init__(self, bucket: str, region: str, client=None):
        if not bucket:
            raise ValueError("OCI_S3_BUCKET is required when OCI_STORE=s3")
        if client is None:
            import boto3
            client = boto3.client("s3", region_name=region)
        self.bucket = bucket
        self.s3 = client

    def put(self, record: SubmissionRecord) -> str:
        key = key_for(record.submission_id)
        self.s3.put_object(Bucket=self.bucket, Key=key,
                           Body=json.dumps(record.to_dict()).encode("utf-8"),
                           ContentType="application/json")
        return key

    def get(self, submission_id: str) -> SubmissionRecord | None:
        try:
            obj = self.s3.get_object(Bucket=self.bucket, Key=key_for(submission_id))
        except self.s3.exceptions.NoSuchKey:
            return None
        return SubmissionRecord.from_dict(json.loads(obj["Body"].read()))

    def _keys(self, prefix: str) -> list[str]:
        keys, token = [], None
        while True:
            kwargs = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            resp = self.s3.list_objects_v2(**kwargs)
            keys += [o["Key"] for o in resp.get("Contents", []) if o["Key"].endswith(".json")]
            if not resp.get("IsTruncated"):
                return keys
            token = resp.get("NextContinuationToken")

    def list_records(self, prefixes: Iterable[str] | None = None) -> list[SubmissionRecord]:
        keys = sorted({k for p in (prefixes or ["submissions/"]) for k in self._keys(p)})
        out = []
        for k in keys:
            obj = self.s3.get_object(Bucket=self.bucket, Key=k)
            out.append(SubmissionRecord.from_dict(json.loads(obj["Body"].read())))
        return out

    def is_empty(self) -> bool:
        resp = self.s3.list_objects_v2(Bucket=self.bucket, Prefix="submissions/", MaxKeys=1)
        return resp.get("KeyCount", 0) == 0


def month_prefixes(date_from: str | None, date_to: str | None) -> list[str] | None:
    """Date-partitioned prefixes covering [from, to] so analytics can avoid a full scan."""
    if not date_from or not date_to:
        return None
    start = datetime.fromisoformat(date_from[:10])
    end = datetime.fromisoformat(date_to[:10])
    if end < start:
        return []
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append("submissions/%04d/%02d/" % (y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def build_store(settings) -> SubmissionStore:
    if settings.store_backend == "s3":
        return S3SubmissionStore(settings.s3_bucket, settings.aws_region)
    return LocalSubmissionStore(settings.local_store_dir)
