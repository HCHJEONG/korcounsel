"""Cookie sessions backed by PostgreSQL; same-origin mutation protection."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr

from klegal_gold.config import ConfigurationError, load_settings
from klegal_gold.db.accounts import Accounts
from klegal_gold.db.session import Database
from klegal_gold.db.site_accounts import SiteAccounts

COOKIE = "korcounsel_session"
router = APIRouter(prefix="/api/auth")


def accounts() -> Accounts:
    settings = load_settings()
    if settings.database_url is None:
        raise HTTPException(503, "인증 저장소가 설정되지 않았습니다.")
    try:
        return SiteAccounts(Database.from_settings(settings), settings)
    except ConfigurationError:
        raise HTTPException(503, "관리자·편집자 계정 설정을 확인하세요.") from None


def same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    # JSON-only POST plus an explicit browser Origin prevents cross-site login/logout.
    expected = load_settings().web_origin
    if origin != expected:
        raise HTTPException(403, "허용되지 않은 요청 출처입니다.")


def require_user(request: Request, service: Annotated[Accounts, Depends(accounts)]) -> UUID:
    token = request.cookies.get(COOKIE, "")
    user = service.session_user(token) if token else None
    if user is None:
        raise HTTPException(401, "로그인이 필요합니다.")
    return user


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=1, max_length=1024)


@router.post("/login", dependencies=[Depends(same_origin)])
def login(
    body: Login,
    request: Request,
    response: Response,
    service: Annotated[Accounts, Depends(accounts)],
) -> dict[str, str]:
    token = service.issue_session(body.username, body.password.get_secret_value())
    if token is None:
        raise HTTPException(401, "아이디 또는 비밀번호를 확인하세요.")
    previous = request.cookies.get(COOKIE)
    if previous:
        service.revoke(previous)
    settings = load_settings()
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=settings.web_origin.startswith("https://"),
        samesite="strict",
        max_age=8 * 3600,
        path="/api",
    )
    return {"status": "ok"}


@router.get("/session")
def session(
    user: Annotated[UUID, Depends(require_user)], service: Annotated[Accounts, Depends(accounts)]
) -> dict[str, str | None]:
    return {
        "user_id": str(user),
        "role": service.role_for(user) if isinstance(service, SiteAccounts) else None,
    }


@router.post("/logout", dependencies=[Depends(same_origin)])
def logout(
    request: Request, response: Response, service: Annotated[Accounts, Depends(accounts)]
) -> dict[str, str]:
    token = request.cookies.get(COOKIE)
    if token:
        service.revoke(token)
    response.delete_cookie(COOKIE, path="/api")
    return {"status": "ok"}
