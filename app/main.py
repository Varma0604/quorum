from contextlib import asynccontextmanager

import jwt
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import JWT_ISSUER, JWT_SECRET
from app.database import Base, SessionLocal, engine, get_db
from app.models import Document, Membership, Revision, User, Workspace
from app.realtime import manager
from app.security import current_user, hash_password, issue_token, verify_password


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    await manager.start()
    try:
        yield
    finally:
        await manager.stop()


app = FastAPI(title="Quorum", description="Real-time collaborative workspace", version="0.1.0", lifespan=lifespan)


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class WorkspaceInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class DocumentInput(BaseModel):
    title: str = Field(min_length=1, max_length=250)
    content: str = ""


class DocumentUpdate(BaseModel):
    content: str
    base_version: int = Field(ge=1)


def require_membership(db: Session, workspace_id: int, user_id: int):
    membership = db.query(Membership).filter_by(workspace_id=workspace_id, user_id=user_id).one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="Workspace membership required")
    return membership


def require_document(db: Session, document_id: int, user: User):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    require_membership(db, document.workspace_id, user.id)
    return document


@app.get("/health")
def health():
    return {"status": "ok", "service": "quorum"}


@app.post("/api/v1/auth/register", status_code=201)
def register(data: Credentials, db: Session = Depends(get_db)):
    email = str(data.email).lower()
    if db.query(User).filter_by(email=email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(email=email, password_hash=hash_password(data.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"user_id": user.id, "email": user.email, "access_token": issue_token(user), "token_type": "bearer"}


@app.post("/api/v1/auth/login")
def login(data: Credentials, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=str(data.email).lower()).one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    return {"access_token": issue_token(user), "token_type": "bearer"}


@app.post("/api/v1/workspaces", status_code=201)
def create_workspace(data: WorkspaceInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace = Workspace(name=data.name, owner_id=user.id)
    workspace.members.append(Membership(user_id=user.id, role="owner"))
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return {"workspace_id": workspace.id, "name": workspace.name, "role": "owner"}


@app.get("/api/v1/workspaces")
def list_workspaces(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(Workspace, Membership.role).join(Membership).filter(Membership.user_id == user.id).all()
    return [{"workspace_id": workspace.id, "name": workspace.name, "role": role} for workspace, role in rows]


@app.post("/api/v1/workspaces/{workspace_id}/members", status_code=201)
def add_member(workspace_id: int, email: EmailStr, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_membership(db, workspace_id, user.id)
    workspace = db.get(Workspace, workspace_id)
    if workspace.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the workspace owner can invite members")
    invited = db.query(User).filter_by(email=str(email).lower()).one_or_none()
    if not invited:
        raise HTTPException(status_code=404, detail="Register the invited user before adding them")
    if db.query(Membership).filter_by(workspace_id=workspace_id, user_id=invited.id).first():
        raise HTTPException(status_code=409, detail="User is already a workspace member")
    membership = Membership(workspace_id=workspace_id, user_id=invited.id, role="member")
    db.add(membership)
    db.commit()
    return {"workspace_id": workspace_id, "user_id": invited.id, "role": "member"}


@app.post("/api/v1/workspaces/{workspace_id}/documents", status_code=201)
def create_document(workspace_id: int, data: DocumentInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_membership(db, workspace_id, user.id)
    document = Document(workspace_id=workspace_id, title=data.title, content=data.content, version=1)
    db.add(document)
    db.flush()
    document.revisions.append(Revision(version=1, content=data.content, edited_by=user.id))
    db.commit()
    db.refresh(document)
    return {"document_id": document.id, "title": document.title, "content": document.content, "version": document.version}


@app.get("/api/v1/documents/{document_id}")
def get_document(document_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    document = require_document(db, document_id, user)
    return {"document_id": document.id, "workspace_id": document.workspace_id, "title": document.title,
            "content": document.content, "version": document.version, "updated_at": document.updated_at}


def save_update(db: Session, document: Document, user_id: int, content: str, base_version: int):
    result = db.query(Document).filter(
        Document.id == document.id, Document.version == base_version
    ).update({
        Document.content: content,
        Document.version: Document.version + 1,
        Document.updated_at: func.now(),
    }, synchronize_session=False)
    if result != 1:
        db.rollback()
        db.refresh(document)
        return None
    document.content = content
    document.version = base_version + 1
    document.revisions.append(Revision(version=document.version, content=content, edited_by=user_id))
    db.commit()
    db.refresh(document)
    return document


@app.put("/api/v1/documents/{document_id}")
def update_document(document_id: int, data: DocumentUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    document = require_document(db, document_id, user)
    saved = save_update(db, document, user.id, data.content, data.base_version)
    if not saved:
        raise HTTPException(status_code=409, detail={"message": "Document changed since this edit began", "current_version": document.version})
    return {"document_id": saved.id, "version": saved.version, "content": saved.content}


@app.get("/api/v1/documents/{document_id}/versions")
def list_versions(document_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    document = require_document(db, document_id, user)
    return [{"version": r.version, "edited_by": r.edited_by, "created_at": r.created_at}
            for r in db.query(Revision).filter_by(document_id=document.id).order_by(Revision.version.desc()).limit(100)]


@app.post("/api/v1/documents/{document_id}/versions/{version}/restore")
def restore_version(document_id: int, version: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    document = require_document(db, document_id, user)
    revision = db.query(Revision).filter_by(document_id=document.id, version=version).one_or_none()
    if not revision:
        raise HTTPException(status_code=404, detail="Version not found")
    restored = save_update(db, document, user.id, revision.content, document.version)
    return {"document_id": restored.id, "version": restored.version, "restored_from": version, "content": restored.content}


@app.websocket("/api/v1/documents/{document_id}/live")
async def live_document(websocket: WebSocket, document_id: int, token: str):
    # Validate the bearer token before accepting the connection, then check workspace access.
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"], issuer=JWT_ISSUER)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        await websocket.close(code=4401, reason="Invalid or expired token")
        return
    with SessionLocal() as db:
        document = db.get(Document, document_id)
        if not document or not db.query(Membership).filter_by(workspace_id=document.workspace_id, user_id=user_id).first():
            await websocket.close(code=4403, reason="Workspace membership required")
            return
    await manager.connect(document_id, websocket)
    await websocket.send_json({"type": "document.connected", "instance_id": manager.instance_id})
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") != "document.update" or not isinstance(message.get("content"), str):
                await websocket.send_json({"type": "error", "message": "Expected document.update with string content"})
                continue
            try:
                update = DocumentUpdate.model_validate(message)
            except Exception:
                await websocket.send_json({"type": "error", "message": "base_version must be a positive integer and content must be text"})
                continue
            with SessionLocal() as db:
                current = db.get(Document, document_id)
                if current is None:
                    await websocket.send_json({"type": "error", "message": "Document no longer exists"})
                    break
                saved = save_update(db, current, user_id, update.content, update.base_version)
                if not saved:
                    await websocket.send_json({"type": "document.conflict", "version": current.version, "content": current.content})
                    continue
                event = {"type": "document.updated", "document_id": saved.id, "version": saved.version,
                         "content": saved.content, "edited_by": user_id}
            await websocket.send_json(event)
            await manager.broadcast_local(document_id, event, sender=websocket)
            await manager.publish_remote(document_id, event)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(document_id, websocket)
