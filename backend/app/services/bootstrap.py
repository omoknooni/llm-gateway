from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import Base, engine
from ..models import ModelAlias, Team, UsageAggregate, UsageEvent, User, VirtualKey
from .costing import estimate_cost_usd


def hash_virtual_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_virtual_key() -> tuple[str, str, str]:
    raw_key = f"vk_{secrets.token_urlsafe(24)}"
    key_hash = hash_virtual_key(raw_key)
    masked = f"{raw_key[:7]}...{raw_key[-4:]}"
    return raw_key, key_hash, masked


def create_schema() -> None:
    Base.metadata.create_all(bind=engine)


def seed_data(db: Session) -> None:
    if db.scalar(select(func.count()).select_from(Team)) not in (None, 0):
        return

    platform_team = Team(name="platform", description="Platform engineering team")
    research_team = Team(name="research", description="Applied AI research team")
    db.add_all([platform_team, research_team])
    db.flush()

    users = [
        User(email="alice@example.internal", name="Alice", team_id=platform_team.id),
        User(email="bob@example.internal", name="Bob", team_id=research_team.id),
    ]
    db.add_all(users)
    db.flush()

    models = [
        ModelAlias(
            alias="claude-sonnet",
            provider="bedrock",
            provider_model_id=settings.bedrock_model_claude_sonnet_id,
            input_cost_per_1k=0.0,
            output_cost_per_1k=0.0,
            active=True,
        ),
        ModelAlias(
            alias="claude-haiku",
            provider="bedrock",
            provider_model_id=settings.bedrock_model_claude_haiku_id,
            input_cost_per_1k=0.0,
            output_cost_per_1k=0.0,
            active=True,
        ),
    ]
    db.add_all(models)
    db.flush()

    raw_key, key_hash, masked = generate_virtual_key()
    sample_key = VirtualKey(
        secret_value=raw_key,
        key_hash=key_hash,
        key_prefix=raw_key[:10],
        masked_key=masked,
        owner_type="team",
        team_id=platform_team.id,
        allowed_model_aliases=["claude-sonnet", "claude-haiku"],
        status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(days=90),
    )
    db.add(sample_key)
    db.flush()

    sonnet = models[0]
    events = [
        UsageEvent(
            team_id=platform_team.id,
            user_id=users[0].id,
            virtual_key_id=sample_key.id,
            model_alias="claude-sonnet",
            provider_model_id=sonnet.provider_model_id,
            request_count=12,
            prompt_tokens=4200,
            completion_tokens=9700,
            total_tokens=13900,
            latency_ms=1200,
            estimated_cost_usd=estimate_cost_usd(4200, 9700, sonnet.input_cost_per_1k, sonnet.output_cost_per_1k),
            success=True,
        ),
        UsageEvent(
            team_id=research_team.id,
            user_id=users[1].id,
            virtual_key_id=sample_key.id,
            model_alias="claude-haiku",
            provider_model_id=models[1].provider_model_id,
            request_count=7,
            prompt_tokens=2200,
            completion_tokens=3300,
            total_tokens=5500,
            latency_ms=820,
            estimated_cost_usd=estimate_cost_usd(2200, 3300, 0.0, 0.0),
            success=True,
        ),
    ]
    db.add_all(events)
    db.commit()
    refresh_usage_aggregates(db)


def refresh_usage_aggregates(db: Session) -> None:
    db.execute(delete(UsageAggregate))
    events = db.scalars(select(UsageEvent)).all()
    buckets: dict[tuple[str, int | None, int | None, int | None, str | None], UsageAggregate] = {}

    for event in events:
        bucket_start = event.created_at.replace(hour=0, minute=0, second=0, microsecond=0)
        key = ("daily", event.team_id, event.user_id, event.virtual_key_id, event.model_alias)
        aggregate = buckets.get(key)
        if aggregate is None:
            aggregate = UsageAggregate(
                bucket_start=bucket_start,
                bucket_granularity="daily",
                team_id=event.team_id,
                user_id=event.user_id,
                virtual_key_id=event.virtual_key_id,
                model_alias=event.model_alias,
                request_count=0,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                estimated_cost_usd=0.0,
                success_count=0,
                failure_count=0,
            )
            buckets[key] = aggregate
        aggregate.request_count += event.request_count
        aggregate.prompt_tokens += event.prompt_tokens
        aggregate.completion_tokens += event.completion_tokens
        aggregate.total_tokens += event.total_tokens
        aggregate.estimated_cost_usd += event.estimated_cost_usd
        if event.success:
            aggregate.success_count += 1
        else:
            aggregate.failure_count += 1

    db.add_all(list(buckets.values()))
    db.commit()
