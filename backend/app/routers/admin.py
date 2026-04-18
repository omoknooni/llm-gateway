from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import ModelAlias, Team, UsageAggregate, UsageEvent, User, VirtualKey
from ..schemas import (
    LeaderboardEntry,
    LoginRequest,
    LoginResponse,
    ModelCreate,
    ModelRead,
    SyncResponse,
    TeamCreate,
    TeamRead,
    UsageSummary,
    UserCreate,
    UserRead,
    VirtualKeyCreate,
    VirtualKeyCreateResponse,
    VirtualKeyRead,
)
from ..security import require_admin
from ..services.bootstrap import generate_virtual_key, refresh_usage_aggregates
from ..services.litellm import litellm_admin_client

router = APIRouter(prefix="/admin", tags=["admin"])
internal_router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest) -> LoginResponse:
    if (
        payload.username != settings.local_admin_username
        or payload.password != settings.local_admin_password
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return LoginResponse(access_token=settings.local_admin_token)


@router.get("/teams", response_model=list[TeamRead], dependencies=[Depends(require_admin)])
def list_teams(db: Session = Depends(get_db)) -> list[Team]:
    return db.scalars(select(Team).order_by(Team.name.asc())).all()


@router.post("/teams", response_model=TeamRead, dependencies=[Depends(require_admin)])
def create_team(payload: TeamCreate, db: Session = Depends(get_db)) -> Team:
    team = Team(name=payload.name, description=payload.description)
    db.add(team)
    db.commit()
    db.refresh(team)
    return team


@router.get("/users", response_model=list[UserRead], dependencies=[Depends(require_admin)])
def list_users(db: Session = Depends(get_db)) -> list[User]:
    return db.scalars(select(User).order_by(User.name.asc())).all()


@router.post("/users", response_model=UserRead, dependencies=[Depends(require_admin)])
def create_user(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    user = User(email=payload.email, name=payload.name, team_id=payload.team_id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/models", response_model=list[ModelRead], dependencies=[Depends(require_admin)])
def list_models(db: Session = Depends(get_db)) -> list[ModelAlias]:
    return db.scalars(select(ModelAlias).order_by(ModelAlias.alias.asc())).all()


@router.post("/models", response_model=ModelRead, dependencies=[Depends(require_admin)])
def create_model(payload: ModelCreate, db: Session = Depends(get_db)) -> ModelAlias:
    record = ModelAlias(**payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/keys", response_model=list[VirtualKeyRead], dependencies=[Depends(require_admin)])
def list_keys(db: Session = Depends(get_db)) -> list[VirtualKey]:
    return db.scalars(select(VirtualKey).order_by(VirtualKey.created_at.desc())).all()


@router.post("/keys", response_model=VirtualKeyCreateResponse, dependencies=[Depends(require_admin)])
def create_key(payload: VirtualKeyCreate, db: Session = Depends(get_db)) -> VirtualKeyCreateResponse:
    raw_key, key_hash, masked = generate_virtual_key()
    record = VirtualKey(
        secret_value=raw_key,
        key_hash=key_hash,
        key_prefix=raw_key[:10],
        masked_key=masked,
        owner_type=payload.owner_type,
        team_id=payload.team_id,
        user_id=payload.user_id,
        allowed_model_aliases=payload.allowed_model_aliases,
        expires_at=payload.expires_at,
        status="active",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return VirtualKeyCreateResponse(key=raw_key, record=record)


@router.post("/keys/{key_id}/rotate", response_model=VirtualKeyCreateResponse, dependencies=[Depends(require_admin)])
def rotate_key(key_id: int, db: Session = Depends(get_db)) -> VirtualKeyCreateResponse:
    current = db.get(VirtualKey, key_id)
    if not current:
        raise HTTPException(status_code=404, detail="Key not found")
    current.status = "rotated"

    raw_key, key_hash, masked = generate_virtual_key()
    replacement = VirtualKey(
        secret_value=raw_key,
        key_hash=key_hash,
        key_prefix=raw_key[:10],
        masked_key=masked,
        owner_type=current.owner_type,
        team_id=current.team_id,
        user_id=current.user_id,
        allowed_model_aliases=current.allowed_model_aliases,
        expires_at=current.expires_at,
        status="active",
        rotated_from_id=current.id,
    )
    db.add(replacement)
    db.commit()
    db.refresh(replacement)
    return VirtualKeyCreateResponse(key=raw_key, record=replacement)


@router.post("/keys/{key_id}/revoke", response_model=VirtualKeyRead, dependencies=[Depends(require_admin)])
def revoke_key(key_id: int, db: Session = Depends(get_db)) -> VirtualKey:
    record = db.get(VirtualKey, key_id)
    if not record:
        raise HTTPException(status_code=404, detail="Key not found")
    record.status = "revoked"
    db.commit()
    db.refresh(record)
    return record


@router.get("/usage", response_model=UsageSummary, dependencies=[Depends(require_admin)])
def usage_summary(
    team_id: int | None = Query(default=None),
    user_id: int | None = Query(default=None),
    model_alias: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
) -> UsageSummary:
    query = select(UsageEvent)
    if team_id is not None:
        query = query.where(UsageEvent.team_id == team_id)
    if user_id is not None:
        query = query.where(UsageEvent.user_id == user_id)
    if model_alias is not None:
        query = query.where(UsageEvent.model_alias == model_alias)
    if since is not None:
        query = query.where(UsageEvent.created_at >= since)

    events = db.scalars(query).all()
    total_requests = sum(event.request_count for event in events)
    prompt_tokens = sum(event.prompt_tokens for event in events)
    completion_tokens = sum(event.completion_tokens for event in events)
    total_tokens = sum(event.total_tokens for event in events)
    total_cost = sum(event.estimated_cost_usd for event in events)
    success_count = sum(1 for event in events if event.success)
    failure_count = sum(1 for event in events if not event.success)
    return UsageSummary(
        total_requests=int(total_requests),
        total_prompt_tokens=int(prompt_tokens),
        total_completion_tokens=int(completion_tokens),
        total_tokens=int(total_tokens),
        total_estimated_cost_usd=float(total_cost),
        success_count=int(success_count),
        failure_count=int(failure_count),
    )


@router.get("/leaderboards", dependencies=[Depends(require_admin)])
def leaderboards(db: Session = Depends(get_db)) -> dict[str, list[LeaderboardEntry]]:
    team_rows = db.execute(
        select(
            Team.name,
            func.coalesce(func.sum(UsageAggregate.request_count), 0),
            func.coalesce(func.sum(UsageAggregate.total_tokens), 0),
            func.coalesce(func.sum(UsageAggregate.estimated_cost_usd), 0.0),
        )
        .join(UsageAggregate, UsageAggregate.team_id == Team.id)
        .group_by(Team.name)
        .order_by(func.sum(UsageAggregate.estimated_cost_usd).desc())
        .limit(10)
    ).all()
    user_rows = db.execute(
        select(
            User.name,
            func.coalesce(func.sum(UsageAggregate.request_count), 0),
            func.coalesce(func.sum(UsageAggregate.total_tokens), 0),
            func.coalesce(func.sum(UsageAggregate.estimated_cost_usd), 0.0),
        )
        .join(UsageAggregate, UsageAggregate.user_id == User.id)
        .group_by(User.name)
        .order_by(func.sum(UsageAggregate.total_tokens).desc())
        .limit(10)
    ).all()
    model_rows = db.execute(
        select(
            UsageAggregate.model_alias,
            func.coalesce(func.sum(UsageAggregate.request_count), 0),
            func.coalesce(func.sum(UsageAggregate.total_tokens), 0),
            func.coalesce(func.sum(UsageAggregate.estimated_cost_usd), 0.0),
        )
        .group_by(UsageAggregate.model_alias)
        .order_by(func.sum(UsageAggregate.request_count).desc())
        .limit(10)
    ).all()

    def to_entries(rows: list[tuple[str, int, int, float]]) -> list[LeaderboardEntry]:
        return [
            LeaderboardEntry(
                label=str(label),
                request_count=int(request_count),
                total_tokens=int(total_tokens),
                estimated_cost_usd=float(cost),
            )
            for label, request_count, total_tokens, cost in rows
        ]

    return {
        "teams": to_entries(team_rows),
        "users": to_entries(user_rows),
        "models": to_entries(model_rows),
    }


@internal_router.post("/litellm/sync", response_model=SyncResponse, dependencies=[Depends(require_admin)])
async def sync_litellm(db: Session = Depends(get_db)) -> SyncResponse:
    keys = db.scalars(select(VirtualKey).where(VirtualKey.status == "active")).all()
    aliases = db.scalars(select(ModelAlias).where(ModelAlias.active.is_(True))).all()
    result = await litellm_admin_client.sync_all(keys=keys, aliases=aliases)
    return SyncResponse(
        synced=result.synced,
        keys_pushed=result.keys_pushed,
        aliases_seen=result.aliases_seen,
        detail=result.detail,
    )


@internal_router.post("/usage/rebuild", dependencies=[Depends(require_admin)])
def rebuild_usage_aggregates(db: Session = Depends(get_db)) -> dict[str, bool]:
    refresh_usage_aggregates(db)
    return {"ok": True}
