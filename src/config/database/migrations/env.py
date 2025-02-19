import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from src.config import settings
from src.config.orm import Base

# Alembic 설정
config = context.config

# 로깅 설정
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


from src.reviews.models.models import *
from src.travel.models.place import Place
from src.travel.models.travel_route_place import TravelRoute, TravelRoutePlace

# ORM 모델의 Metadata
from src.user.models.models import *  # nopa


def get_url() -> str:
    if os.getenv("TEST_ENV") == "true":
        return settings.TEST_ASYNC_DATABASE_URL.replace("asyncpg", "psycopg2")
    return settings.ASYNC_DATABASE_URL.replace("asyncpg", "psycopg2")


# 두 sqlalchemy방식과 SQLModel방식 metadata 병합
target_metadata = Base.metadata

# 비동기 URL을 동기 URL로 변환
sync_url = get_url()


def run_migrations_offline() -> None:
    """오프라인 모드에서 마이그레이션 실행."""
    context.configure(
        url=sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """온라인 모드에서 마이그레이션 실행."""
    # 동기 엔진 생성
    connectable = create_engine(sync_url, echo=True)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


# 온라인 또는 오프라인 모드 선택
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
