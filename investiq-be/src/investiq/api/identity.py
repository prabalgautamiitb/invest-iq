from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from investiq.core.errors import AppError
from investiq.core.security import Principal
from investiq.schemas.identity import (
    CsrfOut,
    EmailInput,
    LoginInput,
    MeOut,
    Message,
    OnboardingInput,
    PreferencesOut,
    PreferencesUpdate,
    PrivacyOut,
    PrivacyUpdate,
    ProfileUpdate,
    QuestionsOut,
    RegisterInput,
    ResetInput,
    SessionOut,
    SubscriptionInput,
    TokenInput,
)
from investiq.services.identity import GENERIC_EMAIL_MESSAGE, IdentityService
from investiq.services.profile_photo import MAX_UPLOAD

router = APIRouter(tags=["identity"])


def service(request: Request) -> IdentityService:
    result: IdentityService = request.app.state.identity
    return result


Service = Annotated[IdentityService, Depends(service)]


def check_origin(request: Request, identity: IdentityService) -> None:
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    if origin is None and referer:
        parsed = urlsplit(referer)
        origin = f"{parsed.scheme}://{parsed.netloc}"
    if (origin is not None and origin not in identity.settings.cors_origins) or (
        request.headers.get("sec-fetch-site") == "cross-site"
    ):
        raise AppError(403, "origin_denied", "Request origin is not allowed")
    # CLI/non-browser requests may omit Origin/Referer, but mutations still need cookie + CSRF.


async def context(request: Request, identity: Service) -> Principal:
    raw = request.cookies.get(identity.settings.cookie_name)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request, identity)
        identity.validate_csrf(raw, request.headers.get("x-csrf-token"))
    return await identity.principal(raw)


Context = Annotated[Principal, Depends(context)]


async def user_context(principal: Context) -> Principal:
    if principal.user_id is None:
        raise AppError(401, "unauthenticated", "Please sign in")
    return principal


UserContext = Annotated[Principal, Depends(user_context)]


async def require_verified(principal: UserContext, identity: Service) -> Principal:
    if not (await identity.me(principal)).email_verified:
        raise AppError(403, "verification_required", "Verify your email to continue")
    return principal


def set_cookie(response: Response, identity: IdentityService, raw: str, *, anonymous: bool) -> None:
    response.set_cookie(
        identity.settings.cookie_name,
        raw,
        httponly=True,
        secure=identity.settings.environment == "production",
        samesite="lax",
        path="/",
        max_age=3600 if anonymous else identity.settings.session_days * 86400,
    )


def clear_cookie(response: Response, identity: IdentityService) -> None:
    response.delete_cookie(
        identity.settings.cookie_name,
        path="/",
        httponly=True,
        secure=identity.settings.environment == "production",
        samesite="lax",
    )


async def limit(
    request: Request,
    identity: IdentityService,
    email: str | None = None,
    *,
    bootstrap: bool = False,
) -> None:
    ip = request.client.host if request.client else "unknown"
    await identity.rate_limit("bootstrap" if bootstrap else "ip", ip, bootstrap=bootstrap)
    if email is not None:
        await identity.rate_limit("email", email)


@router.get("/auth/csrf", response_model=CsrfOut)
async def csrf(request: Request, response: Response, identity: Service) -> CsrfOut:
    check_origin(request, identity)
    await limit(request, identity, bootstrap=True)
    raw, token, created = await identity.bootstrap(
        request.cookies.get(identity.settings.cookie_name)
    )
    if created:
        set_cookie(response, identity, raw, anonymous=True)
    return CsrfOut(csrf_token=token)


@router.post("/auth/register", response_model=MeOut, status_code=201)
async def register(
    data: RegisterInput, request: Request, response: Response, principal: Context, identity: Service
) -> MeOut:
    await limit(request, identity, str(data.email))
    result, raw = await identity.register(principal, data)
    set_cookie(response, identity, raw, anonymous=False)
    return result


@router.post("/auth/login", response_model=MeOut)
async def login(
    data: LoginInput, request: Request, response: Response, principal: Context, identity: Service
) -> MeOut:
    await limit(request, identity, str(data.email))
    result, raw = await identity.login(principal, str(data.email), data.password.get_secret_value())
    set_cookie(response, identity, raw, anonymous=False)
    return result


@router.post("/auth/logout", status_code=204)
async def logout(response: Response, principal: UserContext, identity: Service) -> None:
    await identity.logout(principal)
    clear_cookie(response, identity)


@router.post("/auth/password-reset/request", response_model=Message, status_code=202)
async def request_reset(
    data: EmailInput, request: Request, principal: Context, identity: Service
) -> Message:
    await limit(request, identity, str(data.email))
    await identity.request_token(str(data.email), "password_reset")
    return Message(message=GENERIC_EMAIL_MESSAGE)


@router.post("/auth/verification/request", response_model=Message, status_code=202)
async def request_verification(
    data: EmailInput, request: Request, principal: Context, identity: Service
) -> Message:
    await limit(request, identity, str(data.email))
    await identity.request_token(str(data.email), "verification")
    return Message(message=GENERIC_EMAIL_MESSAGE)


@router.post("/auth/password-reset/complete", response_model=Message)
async def complete_reset(
    data: ResetInput, request: Request, response: Response, principal: Context, identity: Service
) -> Message:
    await limit(request, identity)
    await identity.complete_token(
        data.token.get_secret_value(), "password_reset", data.password.get_secret_value()
    )
    clear_cookie(response, identity)
    return Message(message="Password changed. Sign in with your new password.")


@router.post("/auth/verification/complete", response_model=Message)
async def complete_verification(
    data: TokenInput, request: Request, principal: Context, identity: Service
) -> Message:
    await limit(request, identity)
    await identity.complete_token(data.token.get_secret_value(), "verification")
    return Message(message="Email verified.")


@router.get("/me", response_model=MeOut)
async def me(principal: UserContext, identity: Service) -> MeOut:
    return await identity.me(principal)


@router.patch("/me", response_model=MeOut)
async def patch_me(data: ProfileUpdate, principal: UserContext, identity: Service) -> MeOut:
    return await identity.patch(principal, data)


@router.post("/me/subscription", response_model=MeOut)
async def start_subscription(
    data: SubscriptionInput, principal: UserContext, identity: Service
) -> MeOut:
    return await identity.start_subscription(principal, data)


@router.get("/me/photo")
async def get_photo(principal: UserContext, identity: Service) -> Response:
    return Response(
        content=await identity.photo(principal),
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.put("/me/photo", response_model=MeOut)
async def put_photo(request: Request, principal: UserContext, identity: Service) -> MeOut:
    if request.headers.get("content-type", "").split(";")[0] not in {
        "image/jpeg",
        "image/png",
        "image/webp",
    }:
        raise AppError(415, "invalid_photo_type", "Choose a JPEG, PNG, or WebP photo")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_UPLOAD:
            raise AppError(413, "photo_too_large", "Choose a photo under 1 MB after cropping")
    return await identity.save_photo(principal, bytes(raw))


@router.delete("/me/photo", response_model=MeOut)
async def delete_photo(principal: UserContext, identity: Service) -> MeOut:
    return await identity.save_photo(principal, None)


@router.get("/me/preferences", response_model=PreferencesOut)
async def preferences(principal: UserContext, identity: Service) -> PreferencesOut:
    return (await identity.me(principal)).preferences


@router.patch("/me/preferences", response_model=PreferencesOut)
async def patch_preferences(
    data: PreferencesUpdate, principal: UserContext, identity: Service
) -> PreferencesOut:
    return (await identity.patch(principal, data)).preferences


@router.get("/me/privacy", response_model=PrivacyOut)
async def privacy(principal: UserContext, identity: Service) -> PrivacyOut:
    return (await identity.me(principal)).privacy


@router.patch("/me/privacy", response_model=PrivacyOut)
async def patch_privacy(
    data: PrivacyUpdate, principal: UserContext, identity: Service
) -> PrivacyOut:
    return (await identity.patch(principal, data)).privacy


@router.get("/onboarding/questions", response_model=QuestionsOut)
async def questions(identity: Service) -> QuestionsOut:
    return await identity.questions()


@router.put("/me/onboarding", response_model=MeOut)
async def onboarding(data: OnboardingInput, principal: UserContext, identity: Service) -> MeOut:
    return await identity.onboard(principal, data)


@router.get("/me/sessions", response_model=list[SessionOut])
async def sessions(principal: UserContext, identity: Service) -> list[SessionOut]:
    return await identity.sessions(principal)


@router.delete("/me/sessions/{session_id}", status_code=204)
async def revoke(
    session_id: UUID, response: Response, principal: UserContext, identity: Service
) -> None:
    await identity.revoke(principal, session_id)
    if session_id == principal.session_id:
        clear_cookie(response, identity)


@router.get("/admin/users/{user_id}", response_model=MeOut, tags=["admin"])
async def admin_user(user_id: UUID, principal: UserContext, identity: Service) -> MeOut:
    return await identity.admin_user(principal, user_id)
