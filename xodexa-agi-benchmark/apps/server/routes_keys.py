"""
apps.server.routes_keys
=========================
Provider credentials + validated model names. A key is validated by a live provider
call BEFORE it is accepted, and stored Fernet-encrypted (only last4 + status exposed).
A model name is accepted only if the provider lists it. This is the "legitimate keys +
legitimate models" gate from the spec.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.server import providers, security
from apps.server.db import get_db
from apps.server.deps import audit, csrf_protect, require_verified
from apps.server.models import ProviderCredential, User, UserModel

router = APIRouter(prefix="/api", tags=["credentials"])


class CredentialReq(BaseModel):
    provider: str
    label: str = ""
    key: str = ""
    base_url: str | None = None


class ModelReq(BaseModel):
    credential_id: str
    model_name: str


def _cred_public(c: ProviderCredential) -> dict:
    return {"id": c.id, "provider": c.provider, "label": c.label,
            "key_last4": c.key_last4, "base_url": c.base_url, "status": c.status,
            "validated_at": c.validated_at.isoformat() if c.validated_at else None}


@router.get("/credentials")
def list_credentials(user: User = Depends(require_verified), db: Session = Depends(get_db)):
    rows = db.query(ProviderCredential).filter_by(user_id=user.id).all()
    return {"credentials": [_cred_public(c) for c in rows]}


@router.post("/credentials", dependencies=[Depends(csrf_protect)])
def add_credential(body: CredentialReq, request: Request,
                   user: User = Depends(require_verified), db: Session = Depends(get_db)):
    if body.provider not in providers.PROVIDERS:
        raise HTTPException(422, f"unknown provider; choose one of {list(providers.PROVIDERS)}")
    if providers.PROVIDERS[body.provider]["needs_base_url"] and not body.base_url:
        raise HTTPException(422, "this provider requires a base_url")
    if not body.key and body.provider != "openai-compatible":
        raise HTTPException(422, "an API key is required")
    try:
        res = providers.validate_key(body.provider, body.key, body.base_url)
    except providers.ProviderError as e:
        raise HTTPException(502, str(e))
    if not res.get("ok"):
        audit(db, request, "credential_rejected", user_id=user.id, provider=body.provider)
        raise HTTPException(400, f"key rejected: {res.get('detail')}")

    cred = ProviderCredential(
        user_id=user.id, provider=body.provider, label=body.label[:64],
        key_encrypted=security.encrypt_secret(body.key) if body.key else None,
        key_last4=body.key[-4:] if body.key else "", base_url=body.base_url,
        status="validated", validated_at=security.now())
    db.add(cred)
    db.commit()
    audit(db, request, "credential_added", user_id=user.id, provider=body.provider,
          credential_id=cred.id)
    return {"ok": True, "credential": _cred_public(cred),
            "available_models": res.get("models", [])}


@router.delete("/credentials/{cid}", dependencies=[Depends(csrf_protect)])
def delete_credential(cid: str, request: Request,
                      user: User = Depends(require_verified), db: Session = Depends(get_db)):
    cred = db.query(ProviderCredential).filter_by(id=cid, user_id=user.id).first()
    if not cred:
        raise HTTPException(404, "credential not found")
    db.delete(cred)
    db.commit()
    audit(db, request, "credential_deleted", user_id=user.id, credential_id=cid)
    return {"ok": True}


@router.get("/credentials/{cid}/models")
def credential_models(cid: str, user: User = Depends(require_verified),
                      db: Session = Depends(get_db)):
    cred = db.query(ProviderCredential).filter_by(id=cid, user_id=user.id).first()
    if not cred:
        raise HTTPException(404, "credential not found")
    key = security.decrypt_secret(cred.key_encrypted) if cred.key_encrypted else ""
    try:
        models = providers.list_models(cred.provider, key, cred.base_url)
    except providers.ProviderError as e:
        raise HTTPException(502, str(e))
    return {"models": models}


@router.get("/models")
def list_models(user: User = Depends(require_verified), db: Session = Depends(get_db)):
    rows = db.query(UserModel).filter_by(user_id=user.id).all()
    return {"models": [{"id": m.id, "provider": m.provider, "model_name": m.model_name,
                        "validated": m.validated} for m in rows]}


@router.delete("/models/{mid}", dependencies=[Depends(csrf_protect)])
def delete_model(mid: str, request: Request,
                 user: User = Depends(require_verified), db: Session = Depends(get_db)):
    m = db.query(UserModel).filter_by(id=mid, user_id=user.id).first()
    if not m:
        raise HTTPException(404, "model not found")
    db.delete(m)
    db.commit()
    audit(db, request, "model_deleted", user_id=user.id, model=m.model_name)
    return {"ok": True}


@router.post("/models", dependencies=[Depends(csrf_protect)])
def add_model(body: ModelReq, request: Request,
              user: User = Depends(require_verified), db: Session = Depends(get_db)):
    cred = db.query(ProviderCredential).filter_by(id=body.credential_id, user_id=user.id).first()
    if not cred:
        raise HTTPException(404, "credential not found")
    key = security.decrypt_secret(cred.key_encrypted) if cred.key_encrypted else ""
    model_name = body.model_name.strip()
    if not model_name:
        raise HTTPException(422, "model_name required")
    try:
        ok = providers.validate_model(cred.provider, key, model_name, cred.base_url)
    except providers.ProviderError as e:
        raise HTTPException(502, str(e))
    if not ok:
        raise HTTPException(400, f"model '{model_name}' is not available for this key")
    existing = db.query(UserModel).filter_by(
        user_id=user.id, provider=cred.provider, model_name=model_name).first()
    if existing:
        existing.validated = True
        db.commit()
        m = existing
    else:
        m = UserModel(user_id=user.id, provider=cred.provider, model_name=model_name,
                      validated=True)
        db.add(m)
        db.commit()
    audit(db, request, "model_added", user_id=user.id, provider=cred.provider, model=model_name)
    return {"ok": True, "model": {"id": m.id, "provider": m.provider,
                                  "model_name": m.model_name, "validated": m.validated}}
