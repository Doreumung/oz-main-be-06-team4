import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo

import boto3
import requests  # type: ignore
from apscheduler.schedulers.base import STATE_STOPPED
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import NoCredentialsError
from fastapi import HTTPException, UploadFile
from pytz import timezone  # type: ignore
from sqlalchemy import select

from src import KST
from src.config import settings
from src.reviews.dtos.response import ReviewImageResponse
from src.reviews.models.models import ImageSourceType, Review, ReviewImage
from src.reviews.repo import review_repo
from src.reviews.repo.review_repo import ReviewImageManager, ReviewRepo

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
# 업로드 디렉토리 설정
UPLOAD_DIR = Path("uploads")  # 이미지 저장 경로
UPLOAD_DIR.mkdir(exist_ok=True)  # 디렉토리가 없으면 생성


# 파일 이름 확장자 검증
def validate_file_extension(filename: str) -> None:
    if "." not in filename or filename.rsplit(".", 1)[1].lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File extension must be one of {ALLOWED_EXTENSIONS}",
        )


# 유틸리티 함수: 파일 크기 제한 검증
def validate_file_size(file: UploadFile, max_size_mb: int = 10) -> None:
    """
    파일 크기 검증 함수
    - 파일 크기를 확인하고 최대 크기를 초과하면 예외를 발생시킵니다.
    """
    file.file.seek(0, 2)  # 파일의 끝으로 이동하여 크기를 계산
    file_size = file.file.tell()  # 현재 위치(파일 크기)를 가져옴
    file.file.seek(0)  # 파일의 시작으로 다시 이동

    if file_size > max_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed size is {max_size_mb}MB.",
        )


def validate_url_size(url: str, max_size_mb: int = 10) -> None:
    """
    URL을 통한 이미지 크기 검증 함수.
    - Content-Length 헤더를 사용하여 파일 크기를 검증합니다.
    """
    try:
        response = requests.head(url, allow_redirects=True)
        content_length = response.headers.get("Content-Length")

        if content_length and int(content_length) > max_size_mb * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail=f"URL file too large. Maximum allowed size is {max_size_mb}MB.",
            )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to validate URL size: {str(e)}",
        )


# 데이터 검증 유틸
def validate_source_type(source_type: str) -> ImageSourceType:

    try:
        return ImageSourceType(source_type)
    except ValueError:
        raise ValueError(f"Invalid source_type: {source_type}. Must be one of {[e.value for e in ImageSourceType]}")


# async def delete_file_from_s3(filepath: str):
AWS_ACCESS_KEY = settings.AWS_ACCESS_KEY
AWS_SECRET_KEY = settings.AWS_SECRET_KEY
AWS_REGION = settings.AWS_REGION
BUCKET_NAME = settings.BUCKET_NAME
transfer_config = TransferConfig(multipart_threshold=10 * 1024 * 1024)


async def handle_image_urls(uploaded_urls: List[str], deleted_urls: List[str], user_id: str) -> List[ReviewImage]:
    """
    업로드된 URL은 그대로 유지하고, 삭제된 URL은 S3에서 제거
    """
    if not user_id:
        raise ValueError("user_id is required")

    # 삭제된 URL 처리
    for url in deleted_urls:
        key = url.split("/")[-1]
        try:
            s3_client.delete_object(Bucket=BUCKET_NAME, Key=key)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete image: {e}")

    # 업로드된 URL을 ReviewImage 객체로 변환
    review_images = [
        ReviewImage(user_id=user_id, filepath=url, source_type=ImageSourceType.UPLOAD, is_temporary=True)
        for url in uploaded_urls
    ]

    return review_images


s3_client = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=AWS_REGION,
)


async def handle_file_or_url(
    file: Optional[UploadFile], url: Optional[str], user_id: str, image_repo: ReviewRepo
) -> tuple[str, ImageSourceType]:
    """
    파일 또는 URL을 처리하고, S3에 업로드한 URL을 반환합니다.
    임시 저장된 ReviewImage 객체를 DB에 저장합니다.
    """
    if not file and not url:
        raise HTTPException(status_code=400, detail="No file or URL provided")

    if file:
        # 파일 검증 및 업로드
        if not file.filename:
            raise HTTPException(status_code=400, detail="Invalid file: Filename cannot be None")
        validate_file_extension(file.filename)
        validate_file_size(file)

        unique_filename = f"{user_id}/{uuid.uuid4().hex}_{file.filename}"
        file_location = Path(f"uploads/{unique_filename}")
        file_location.parent.mkdir(parents=True, exist_ok=True)

        # 파일을 로컬에 저장
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # S3 업로드
        try:
            with open(file_location, "rb") as file_to_upload:
                s3_client.upload_fileobj(
                    file_to_upload,
                    BUCKET_NAME,
                    unique_filename,
                    Config=transfer_config,
                    ExtraArgs={"Metadata": {"user_name": user_id}},
                )
            s3_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{unique_filename}"

            # 데이터베이스에 이미지 정보 저장
            image = ReviewImage(
                review_id=None,  # 아직 리뷰와 연결되지 않음
                user_id=user_id,
                filepath=s3_url,
                source_type=ImageSourceType.UPLOAD,
                is_temporary=True,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            await image_repo.save_image(image)

            return s3_url, ImageSourceType.UPLOAD
        except NoCredentialsError:
            raise HTTPException(status_code=500, detail="AWS credentials not available")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")

    elif url:
        # URL 검증 및 처리
        validate_url_size(url)
        filename = url.split("/")[-1]
        validate_file_extension(filename)

        unique_filename = f"{user_id}/{uuid.uuid4().hex}_{filename}"
        try:
            response = requests.get(url, stream=True)
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to fetch URL content")

            # S3 업로드
            s3_client.upload_fileobj(
                response.raw,
                BUCKET_NAME,
                unique_filename,
                Config=transfer_config,
                ExtraArgs={"Metadata": {"user_name": user_id}},
            )
            s3_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{unique_filename}"

            # 데이터베이스에 이미지 정보 저장
            image = ReviewImage(
                review_id=None,
                user_id=user_id,
                filepath=s3_url,  # S3 URL 저장
                source_type=ImageSourceType.LINK,
                is_temporary=True,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            await image_repo.save_image(image)

            return s3_url, ImageSourceType.LINK
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"URL processing failed: {str(e)}")

    raise HTTPException(status_code=400, detail="Failed to process file or URL")


# 이미지 삭제 요청 처리 함수
async def process_image_deletion(url: str, review_image_manager: ReviewImageManager) -> None:
    try:
        s3_key = url.split("/")[-1]
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=s3_key)
        review_image_manager.add_deleted_url(url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete image: {str(e)}")


async def delete_file(image: ReviewImage) -> ReviewImage:
    """
    이미지 삭제 처리 함수
    - 로컬 파일 또는 S3에서 파일 삭제
    """
    if image.source_type == ImageSourceType.UPLOAD:
        file_path = Path(image.filepath)
        if file_path.exists():
            file_path.unlink()
            print(f"Local file deleted: {file_path}")  # 디버깅 로그
    elif image.source_type == ImageSourceType.LINK:
        key = Path(image.filepath).name
        try:
            s3_client.delete_object(Bucket="bucket-name", Key=key)
            print(f"S3 file deleted: {key}")  # 디버깅 로그
        except Exception as e:
            print(f"Failed to delete S3 file: {key}, error: {e}")  # 디버깅 로그

    return image


from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler(timezone=timezone("Asia/Seoul"))


async def cleanup_temporary_images(image_repo: ReviewRepo) -> None:
    """
    일정 시간이 지난 임시 이미지를 정리
    """
    cutoff_time = datetime.now(ZoneInfo("Asia/Seoul")) - timedelta(hours=1)
    query = select(ReviewImage).where(ReviewImage.is_temporary == True, ReviewImage.created_at < cutoff_time)  # type: ignore
    result = await image_repo.session.execute(query)

    images = result.scalars().all()

    for image in images:
        try:
            # 파일 삭제
            await delete_file(image)
            # 데이터베이스에서 삭제
            await image_repo.delete_image(image.id)
        except Exception as e:
            print(f"Failed to cleanup image {image.id}: {e}")


def start_scheduler(image_repo: ReviewRepo) -> None:
    """
    스케줄러 시작 함수
    """
    if scheduler.running:
        print("Scheduler is already running")
        return  # 실행 중이면 중단

    print(f"Attempting to start scheduler with image_repo: {image_repo}")
    scheduler.add_job(
        cleanup_temporary_images,
        "interval",
        hours=1,
        kwargs={"image_repo": image_repo},
    )
    scheduler.start()
    print("Scheduler started")


def stop_scheduler() -> None:
    """
    스케줄러 정지 함수
    """
    scheduler.shutdown()
    print("Scheduler stopped")
