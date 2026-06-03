"""
apps.server.routes_auth
=========================
Registration with email verification, login/logout, and session introspection.
Only verified users can add credentials or launch runs (enforced in other routers).
"""

from __future__ import annotations

import datetime as dt
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.server import email as mailer, security
from apps.server.config import get_settings
from apps.server.db import get_db
from apps.server.deps import audit, client_ip, rate_limit
from apps.server.models import EmailVerification, SessionRow, User

router = APIRouter(prefix="/api/auth", tags=["auth"])
_settings = get_settings()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USER_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


class RegisterReq(BaseModel):
    username: str
    email: str
    password: str


class LoginReq(BaseModel):
    identifier: str   # username or email
    password: str


class ResendReq(BaseModel):
    email: str


def _issue_verification(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(EmailVerification(
        user_id=user.id, token=token,
        expires_at=security.now() + dt.timedelta(hours=_settings.verification_ttl_hours)))
    db.commit()
    return f"{_settings.public_base_url.rstrip('/')}/api/auth/verify?token={token}"


def _set_session(db: Session, resp: Response, user: User, request: Request) -> str:
    cookie_tok, token_hash = security.new_session_token()
    db.add(SessionRow(user_id=user.id, token_hash=token_hash,
                      expires_at=security.session_expiry(), ip=client_ip(request),
                      user_agent=(request.headers.get("user-agent") or "")[:256]))
    db.commit()
    resp.set_cookie(_settings.cookie_name, cookie_tok, httponly=True, samesite="lax",
                    secure=_settings.cookie_secure, max_age=_settings.session_ttl_hours * 3600,
                    path="/")
    return cookie_tok


@router.post("/register")
def register(body: RegisterReq, request: Request, db: Session = Depends(get_db)):
    rate_limit(request, "register", limit=5, window=300)
    username = body.username.strip()
    email = body.email.strip().lower()
    if not _USER_RE.match(username):
        raise HTTPException(422, "username must be 3-32 chars (letters, digits, . _ -)")
    if not _EMAIL_RE.match(email):
        raise HTTPException(422, "a valid email address is required")
    if len(body.password) < 8:
        raise HTTPException(422, "password must be at least 8 characters")
    if db.query(User).filter_by(email=email).first():
        raise HTTPException(409, "an account with this email already exists")
    if db.query(User).filter_by(username=username).first():
        raise HTTPException(409, "username is taken")

    user = User(username=username, email=email,
                password_hash=security.hash_password(body.password))
    db.add(user)
    db.commit()
    link = _issue_verification(db, user)
    sent = mailer.send_verification(email, username, link)
    audit(db, request, "register", user_id=user.id, email=email)
    return {"ok": True, "email_sent": sent,
            "message": "Registered. Check your email to verify your account."
                       + ("" if sent else " (SMTP not configured — see server logs for the link.)")}


@router.get("/verify")
def verify(token: str, request: Request, db: Session = Depends(get_db)):
    base = _settings.public_base_url.rstrip("/")
    row = db.query(EmailVerification).filter_by(token=token).first()
    if not row or row.consumed_at is not None or security._aware(row.expires_at) < security.now():
        return RedirectResponse(f"{base}/verify.html?status=invalid", status_code=303)
    user = db.get(User, row.user_id)
    user.email_verified = True
    row.consumed_at = security.now()
    db.commit()
    audit(db, request, "email_verified", user_id=user.id)
    return RedirectResponse(f"{base}/verify.html?status=success", status_code=303)


@router.post("/resend")
def resend(body: ResendReq, request: Request, db: Session = Depends(get_db)):
    rate_limit(request, "resend", limit=3, window=300)
    user = db.query(User).filter_by(email=body.email.strip().lower()).first()
    # Always return ok (don't leak which emails exist).
    if user and not user.email_verified:
        link = _issue_verification(db, user)
        mailer.send_verification(user.email, user.username, link)
    return {"ok": True, "message": "If that account exists and is unverified, a new link was sent."}


@router.post("/login")
def login(body: LoginReq, request: Request, response: Response, db: Session = Depends(get_db)):
    rate_limit(request, "login", limit=10, window=300)
    ident = body.identifier.strip().lower()
    user = (db.query(User).filter_by(email=ident).first()
            or db.query(User).filter_by(username=body.identifier.strip()).first())
    if not user or not security.verify_password(body.password, user.password_hash):
        raise HTTPException(401, "invalid credentials")
    if not user.email_verified:
        raise HTTPException(403, "please verify your email before logging in")
    tok = _set_session(db, response, user, request)
    audit(db, request, "login", user_id=user.id)
    return {"ok": True, "user": _public(user), "csrf_token": security.csrf_for(tok)}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    tok = request.cookies.get(_settings.cookie_name)
    if tok:
        row = db.query(SessionRow).filter_by(token_hash=security._hash_token(tok)).first()
        if row:
            row.revoked_at = security.now()
            db.commit()
    response.delete_cookie(_settings.cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    user = security.current_user(request, db)
    if not user:
        return {"authenticated": False}
    tok = request.cookies.get(_settings.cookie_name)
    return {"authenticated": True, "user": _public(user),
            "csrf_token": security.csrf_for(tok)}


def _public(user: User) -> dict:
    return {"id": user.id, "username": user.username, "email": user.email,
            "email_verified": user.email_verified, "is_admin": user.is_admin}
