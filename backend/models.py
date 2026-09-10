from datetime import datetime
from sqlalchemy import String, Integer, Float, Text, DateTime, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.database import Base

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    tasks: Mapped[list["ScreeningTask"]] = relationship(back_populates="owner")
    annotation_schemas: Mapped[list["AnnotationSchema"]] = relationship(back_populates="owner", foreign_keys="AnnotationSchema.owner_id")
    active_annotation_schema_id: Mapped[int | None] = mapped_column(
        ForeignKey("annotation_schemas.id"), nullable=True
    )

class AnnotationSchema(Base):
    __tablename__ = "annotation_schemas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    gse_labels: Mapped[str] = mapped_column(Text, nullable=False)
    gsm_labels: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    owner: Mapped["User"] = relationship(back_populates="annotation_schemas", foreign_keys=[owner_id])

class CriteriaTemplate(Base):
    __tablename__ = "criteria_templates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    criteria_text: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ScreeningTask(Base):
    __tablename__ = "screening_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # csv | geo
    search_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|running|done|error
    total: Mapped[int] = mapped_column(Integer, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    included_count: Mapped[int] = mapped_column(Integer, default=0)
    excluded_count: Mapped[int] = mapped_column(Integer, default=0)
    uncertain_count: Mapped[int] = mapped_column(Integer, default=0)
    criteria_text: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    label_schema: Mapped[str | None] = mapped_column(Text, nullable=True)
    annotation_schema_id: Mapped[int | None] = mapped_column(ForeignKey("annotation_schemas.id"), nullable=True)
    task_type: Mapped[str] = mapped_column(String(32), default="screening")
    parent_task_id: Mapped[int | None] = mapped_column(ForeignKey("screening_tasks.id"), nullable=True)
    owner: Mapped["User"] = relationship(back_populates="tasks")
    results: Mapped[list["ScreeningResult"]] = relationship(back_populates="task")

class ScreeningResult(Base):
    __tablename__ = "screening_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("screening_tasks.id"), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    keyword_matched: Mapped[bool] = mapped_column(default=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=True)  # include|exclude|uncertain
    confidence: Mapped[float] = mapped_column(Float, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    rule_checks: Mapped[str] = mapped_column(Text, nullable=True)  # JSON string
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|done|error
    error_msg: Mapped[str] = mapped_column(Text, nullable=True)
    gse_type: Mapped[str | None] = mapped_column(String(256), nullable=True)
    pubdate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    update_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    has_raw_data: Mapped[bool] = mapped_column(default=False)
    n_samples: Mapped[int] = mapped_column(Integer, default=0)
    pmid: Mapped[str | None] = mapped_column(String(32), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(256), nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pdf_status: Mapped[str] = mapped_column(String(16), default="none")  # none|fetching|available|failed
    original_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    original_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    samples: Mapped[list["GeoSample"]] = relationship(back_populates="result", cascade="all, delete-orphan")
    labels: Mapped[list["GeoLabel"]] = relationship(back_populates="result", cascade="all, delete-orphan")
    task: Mapped["ScreeningTask"] = relationship(back_populates="results")

class LLMConfig(Base):
    __tablename__ = "llm_configs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    api_key: Mapped[str] = mapped_column(String(512), nullable=True)
    base_url: Mapped[str] = mapped_column(String(256), nullable=True)
    model: Mapped[str] = mapped_column(String(128), nullable=True)
    temperature: Mapped[float] = mapped_column(Float, default=0.1)
    __table_args__ = (UniqueConstraint("owner_id", "provider"),)

class GeoSample(Base):
    __tablename__ = "geo_samples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("screening_results.id"), nullable=False)
    gsm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    organism: Mapped[str | None] = mapped_column(String(128), nullable=True)
    biosample_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cell_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    labels: Mapped[list["GsmLabel"]] = relationship(back_populates="sample", cascade="all, delete-orphan")
    result: Mapped["ScreeningResult"] = relationship(back_populates="samples")

class GeoLabel(Base):
    __tablename__ = "geo_labels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("screening_results.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="llm")
    result: Mapped["ScreeningResult"] = relationship(back_populates="labels")

class Library(Base):
    __tablename__ = "libraries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    entries: Mapped[list["LibraryEntry"]] = relationship(back_populates="library", cascade="all, delete-orphan")


class LibraryEntry(Base):
    __tablename__ = "library_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    library_id: Mapped[int] = mapped_column(ForeignKey("libraries.id"), nullable=False)
    gse_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    organism: Mapped[str | None] = mapped_column(String(128), nullable=True)
    n_samples: Mapped[int] = mapped_column(Integer, default=0)
    gse_type: Mapped[str | None] = mapped_column(String(256), nullable=True)
    has_raw_data: Mapped[bool] = mapped_column(default=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    pubdate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    update_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="new")
    source: Mapped[str] = mapped_column(String(16), default="search")
    task_id: Mapped[int | None] = mapped_column(ForeignKey("screening_tasks.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    library: Mapped["Library"] = relationship(back_populates="entries")
    labels: Mapped[list["LibraryEntryLabel"]] = relationship(back_populates="entry", cascade="all, delete-orphan")
    samples: Mapped[list["LibraryEntrySample"]] = relationship(back_populates="entry", cascade="all, delete-orphan")


class LibraryEntryLabel(Base):
    __tablename__ = "library_entry_labels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("library_entries.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="human")
    entry: Mapped["LibraryEntry"] = relationship(back_populates="labels")


class LibraryEntrySample(Base):
    __tablename__ = "library_entry_samples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("library_entries.id"), nullable=False)
    gsm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    organism: Mapped[str | None] = mapped_column(String(128), nullable=True)
    biosample_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cell_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry: Mapped["LibraryEntry"] = relationship(back_populates="samples")


class GsmLabel(Base):
    __tablename__ = "gsm_labels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sample_id: Mapped[int] = mapped_column(ForeignKey("geo_samples.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="llm")
    sample: Mapped["GeoSample"] = relationship(back_populates="labels")


# v2: source IDs are snapshots, not foreign keys, so deleting a screening task
# does not delete or prevent access to an independently reviewed protocol.
class ProtocolJob(Base):
    __tablename__ = "protocol_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_task_id: Mapped[int] = mapped_column(Integer)
    extraction_unit: Mapped[str] = mapped_column(String(16), default='article', server_default='article')
    name: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProtocolItem(Base):
    __tablename__ = "protocol_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("protocol_jobs.id"), index=True)
    source_result_id: Mapped[int] = mapped_column(Integer)
    snapshot_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="waiting_material")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    active_revision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("job_id", "source_result_id"),)


class ProtocolSample(Base):
    __tablename__ = "protocol_samples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("protocol_items.id"), index=True)
    gsm_id: Mapped[str] = mapped_column(String(64))
    snapshot_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="waiting_material")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    active_revision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("item_id", "gsm_id"),)


class ProtocolDocument(Base):
    __tablename__ = "protocol_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("protocol_items.id"), index=True)
    name: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(32), default="main")
    reference: Mapped[str] = mapped_column(Text, default="")
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    pages_json: Mapped[str] = mapped_column(Text)
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("item_id", "sha256"),)


class ProtocolRevision(Base):
    __tablename__ = "protocol_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("protocol_items.id"), index=True)
    sample_id: Mapped[int | None] = mapped_column(ForeignKey("protocol_samples.id"), nullable=True, index=True)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(16))  # machine | human
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    payload_json: Mapped[str] = mapped_column(Text)
    provenance_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
