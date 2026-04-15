from datetime import datetime
from sqlalchemy import String, Integer, Float, Text, DateTime, ForeignKey
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
    samples: Mapped[list["GeoSample"]] = relationship(back_populates="result", cascade="all, delete-orphan")
    labels: Mapped[list["GeoLabel"]] = relationship(back_populates="result", cascade="all, delete-orphan")
    task: Mapped["ScreeningTask"] = relationship(back_populates="results")

class LLMConfig(Base):
    __tablename__ = "llm_configs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="deepseek")
    base_url: Mapped[str] = mapped_column(String(256), nullable=True)
    api_key: Mapped[str] = mapped_column(String(256), nullable=True)
    model: Mapped[str] = mapped_column(String(128), default="deepseek-chat")
    temperature: Mapped[float] = mapped_column(Float, default=0.1)

class GeoSample(Base):
    __tablename__ = "geo_samples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("screening_results.id"), nullable=False)
    gsm_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    organism: Mapped[str | None] = mapped_column(String(128), nullable=True)
    biosample_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cell_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped["ScreeningResult"] = relationship(back_populates="samples")

class GeoLabel(Base):
    __tablename__ = "geo_labels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("screening_results.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="llm")
    result: Mapped["ScreeningResult"] = relationship(back_populates="labels")
