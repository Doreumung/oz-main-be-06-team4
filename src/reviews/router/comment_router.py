from datetime import datetime
from typing import List
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, status
from fastapi.routing import APIRouter
from sqlalchemy import Integer, cast
from sqlalchemy.sql import select

from src.reviews.dtos.request import CommentRequest
from src.reviews.dtos.response import (
    CommentResponse,
    GetCommentResponse,
    UpdateCommentResponse,
)
from src.reviews.models.models import Comment, Review
from src.reviews.repo import review_repo
from src.reviews.repo.review_repo import CommentRepo, ReviewRepo
from src.user.repo.repository import UserRepository
from src.user.services.authentication import authenticate

comment_router = APIRouter(prefix="/api/v1", tags=["Comments"])


# 댓글 생성
@comment_router.post(
    "/reviews/{review_id}/comment",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    review_id: int,
    body: CommentRequest,
    user_id: str = Depends(authenticate),
    user_repo: UserRepository = Depends(CommentRepo),
    comment_repo: CommentRepo = Depends(),
) -> CommentResponse:
    # 사용자 확인
    user = await user_repo.get_user_by_id(user_id=user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    query = select(Review).where(cast(Review.id, Integer) == review_id)
    result = await comment_repo.session.execute(query)
    review = result.unique().scalar_one_or_none()
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review does not exist",
        )

    # 댓글 생성
    new_comment = Comment(
        user_id=user.id,
        review_id=review.id,
        content=body.content,
    )
    await comment_repo.create_comment(comment=new_comment)
    return CommentResponse(
        comment_id=new_comment.id,
        nickname=user.nickname,
        review_id=review.id,
        content=new_comment.content,
        created_at=new_comment.created_at,
    )


# 특정 리뷰 댓글 목록 조회
@comment_router.get(
    "/reviews/{review_id}/comment",
    response_model=GetCommentResponse,
    status_code=status.HTTP_200_OK,
)
async def get_comment(
    review_id: int,
    comment_repo: CommentRepo = Depends(),
    user_repo: UserRepository = Depends(),  # 사용자 정보를 조회하기 위한 repository
) -> List[GetCommentResponse]:
    # 댓글 조회 쿼리
    query = select(Comment).where(cast(Comment.review_id, Integer) == review_id)
    result = await comment_repo.session.execute(query)
    comments = result.scalars().all()

    # 댓글 리스트 반환, 각 댓글마다 작성자의 nickname을 포함
    response = []
    for comment in comments:
        # 댓글을 작성한 사용자 조회
        user = await user_repo.get_user_by_id(user_id=comment.user_id)

        # 사용자가 있을 경우 nickname을 추가, 없을 경우 None을 반환
        response.append(
            GetCommentResponse(
                comment_id=comment.id,
                nickname=user.nickname,  # type: ignore
                content=comment.content,
                created_at=comment.created_at,
            )
        )

    return response


# 댓글 수정
@comment_router.patch(
    "/comments/{comment_id}",
    response_model=UpdateCommentResponse,
    status_code=status.HTTP_200_OK,
)
async def update_comment(
    comment_id: int,
    body: CommentRequest,
    user_id: str = Depends(authenticate),
    user_repo: UserRepository = Depends(),
    review_repo: ReviewRepo = Depends(),
    comment_repo: CommentRepo = Depends(),
) -> UpdateCommentResponse:
    user = await user_repo.get_user_by_id(user_id=user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    result = await comment_repo.session.execute(select(Comment).where(cast(Comment.id, Integer) == comment_id))
    comment = result.scalar_one_or_none()

    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment does not exist",
        )

    review = await review_repo.get_review_by_id(comment.review_id)

    if not review:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review does not exist",
        )

    # 권한 확인
    if comment.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action",
        )
    # 댓글 수정
    comment.content = body.content
    comment.updated_at = datetime.now()

    await comment_repo.create_comment(comment=comment)
    return UpdateCommentResponse(
        comment_id=comment.id,
        nickname=user.nickname,
        content=comment.content,
        updated_at=comment.updated_at,
        message="댓글이 성공적으로 수정되었습니다",
    )


# 댓글 삭제
@comment_router.delete(
    "/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_comment(
    comment_id: int,
    user_id: str = Depends(authenticate),
    user_repo: UserRepository = Depends(),
    comment_repo: CommentRepo = Depends(),
) -> None:
    user = await user_repo.get_user_by_id(user_id=user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # 댓글 조회
    query = select(Comment).where(cast(Comment.id, Integer) == comment_id)
    result = await comment_repo.session.execute(query)
    comment = result.scalar_one_or_none()

    # 댓글이 없을 경우 예외 처리
    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comment does not exist",
        )

    # 권한 확인
    if comment.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action",
        )

    # 댓글 삭제
    await comment_repo.delete_comment(comment.id)  # ID를 전달
