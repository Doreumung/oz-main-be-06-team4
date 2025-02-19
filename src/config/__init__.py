import os
from enum import StrEnum

from dotenv import load_dotenv
from pydantic_settings import BaseSettings


class ServerEnv(StrEnum):
    LOCAL = "local"  # 내 로컬 환경
    DEV = "dev"  # 개발 서버
    PROD = "prod"  # 프로덕션 서버


class Settings(BaseSettings):
    ASYNC_DATABASE_URL: str
    TEST_ASYNC_DATABASE_URL: str
    KAKAO_REST_API_KEY: str
    KAKAO_REDIRECT_URL: str
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URL: str
    SECRET_KEY: str
    DEBUG: bool
    AWS_ACCESS_KEY: str
    AWS_SECRET_KEY: str
    AWS_REGION: str
    BUCKET_NAME: str

    class Config:
        env_file = ".env.dev"


def load_environment_variables(env: ServerEnv) -> None:
    """
    주어진 환경에 따라 환경 변수를 로드합니다.
    """
    env_file = None
    match env:
        case ServerEnv.DEV:
            env_file = "src/config/.env.dev"
        case ServerEnv.PROD:
            env_file = "src/config/.env.prod"
        case _:
            env_file = "src/config/.env.local"  # 수정된 경로
    if os.getenv("ON_CI") == "true":
        env_file = "src/config/.env.ci"
    # .env 파일 경로가 정확한지 확인하고 로드합니다.
    if env_file:
        # .env 파일이 없으면 오류를 발생시킬 수 있습니다.
        if not load_dotenv(dotenv_path=env_file):
            raise FileNotFoundError(f"{env_file} 파일을 찾을 수 없습니다.")
        print(f"{env_file} 환경 변수 로드 완료.")


def get_settings(env: ServerEnv) -> Settings:
    # 환경 변수를 먼저 로드
    load_environment_variables(env)
    # Settings 인스턴스를 반환
    return Settings()  # type: ignore


# 환경 변수에서 ENV 값을 가져오거나 DEV를 기본값으로 사용
ENV = os.getenv("ENV", ServerEnv.DEV)  # ENV가 설정되지 않으면 DEV가 기본값
settings = get_settings(env=ServerEnv(ENV))

# settings가 제대로 로드되었는지 확인
print(f"Loaded settings for environment: {ENV}")
