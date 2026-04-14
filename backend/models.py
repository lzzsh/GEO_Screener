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
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|running|done|error
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    criteria_text: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    owner: Mapped["User"] = relationship(back_populates="tasks")
    results: Mapped[list["ScreeningResult"]] = relationship(back_populates="task")

class ScreeningResult(Base):
    __tablename__ = "screening_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("screening_tasks.id"), nullable=False)
    dataset_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=True)  # include|exclude|uncertain
    confidence: Mapped[float] = mapped_column(Float, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    rule_checks: Mapped[str] = mapped_column(Text, nullable=True)  # JSON string
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|done|error
    error_msg: Mapped[str] = mapped_column(Text, nullable=True)
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
