"""Menu API: sidebar group/item CRUD + tab registry."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user, require_permission
from app.models import MenuGroup, MenuItem
from app.menu_registry import TAB_REGISTRY

router = APIRouter(
    prefix="/menu",
    tags=["menu"],
    dependencies=[Depends(get_current_user)],  # login required for all
)


# ── GET /menu ────────────────────────────────────────────────────────────────

def _item_dict(item: MenuItem) -> dict:
    meta = TAB_REGISTRY.get(item.tab_key, {})
    return {
        "id": item.id,
        "group_id": item.group_id,
        "tab_key": item.tab_key,
        "label": meta.get("label", item.tab_key),
        "icon": meta.get("icon", ""),
        "permission": meta.get("permission", ""),
        "superadmin_only": meta.get("superadmin_only", False),
        "sort_order": item.sort_order,
    }


def _group_dict(group: MenuGroup) -> dict:
    return {
        "id": group.id,
        "name": group.name,
        "icon": group.icon,
        "sort_order": group.sort_order,
        "is_active": group.is_active,
        "items": [_item_dict(i) for i in group.items],
    }


@router.get("")
def get_menu(db: Session = Depends(get_db)):
    groups = (
        db.query(MenuGroup)
        .filter(MenuGroup.is_active.is_(True))
        .order_by(MenuGroup.sort_order, MenuGroup.id)
        .all()
    )
    return {"groups": [_group_dict(g) for g in groups]}


# ── POST /menu/groups ────────────────────────────────────────────────────────

class _GroupCreate(BaseModel):
    name: str
    icon: str = ""
    sort_order: int = 0


@router.post("/groups", dependencies=[Depends(require_permission("menu.manage"))])
def create_group(body: _GroupCreate, db: Session = Depends(get_db)):
    max_order = db.query(func.max(MenuGroup.sort_order)).scalar() or 0
    g = MenuGroup(name=body.name, icon=body.icon, sort_order=body.sort_order or max_order + 1)
    db.add(g)
    db.commit()
    db.refresh(g)
    return _group_dict(g)


# ── PATCH /menu/groups/{id} ──────────────────────────────────────────────────

class _GroupUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


@router.patch("/groups/{group_id}", dependencies=[Depends(require_permission("menu.manage"))])
def update_group(group_id: int, body: _GroupUpdate, db: Session = Depends(get_db)):
    g = db.query(MenuGroup).get(group_id)
    if not g:
        raise HTTPException(404, "Group not found")
    for field in ("name", "icon", "sort_order", "is_active"):
        val = getattr(body, field)
        if val is not None:
            setattr(g, field, val)
    db.commit()
    db.refresh(g)
    return _group_dict(g)


# ── DELETE /menu/groups/{id} ─────────────────────────────────────────────────

@router.delete("/groups/{group_id}", dependencies=[Depends(require_permission("menu.manage"))])
def delete_group(group_id: int, db: Session = Depends(get_db)):
    g = db.query(MenuGroup).get(group_id)
    if not g:
        raise HTTPException(404, "Group not found")
    db.delete(g)  # cascade deletes items
    db.commit()
    return {"ok": True}


# ── POST /menu/items ─────────────────────────────────────────────────────────

class _ItemCreate(BaseModel):
    group_id: int
    tab_key: str
    sort_order: int = 0


@router.post("/items", dependencies=[Depends(require_permission("menu.manage"))])
def create_item(body: _ItemCreate, db: Session = Depends(get_db)):
    if body.tab_key not in TAB_REGISTRY:
        raise HTTPException(422, f"Unknown tab_key: {body.tab_key}")
    g = db.query(MenuGroup).get(body.group_id)
    if not g:
        raise HTTPException(404, "Group not found")
    dup = db.query(MenuItem).filter_by(group_id=body.group_id, tab_key=body.tab_key).first()
    if dup:
        raise HTTPException(409, f"Tab '{body.tab_key}' already in group '{g.name}'")
    max_order = db.query(func.max(MenuItem.sort_order)).filter_by(group_id=body.group_id).scalar() or 0
    item = MenuItem(group_id=body.group_id, tab_key=body.tab_key, sort_order=body.sort_order or max_order + 1)
    db.add(item)
    db.commit()
    db.refresh(item)
    return _item_dict(item)


# ── PATCH /menu/items/{id} ──────────────────────────────────────────────────

class _ItemUpdate(BaseModel):
    sort_order: Optional[int] = None
    group_id: Optional[int] = None


@router.patch("/items/{item_id}", dependencies=[Depends(require_permission("menu.manage"))])
def update_item(item_id: int, body: _ItemUpdate, db: Session = Depends(get_db)):
    item = db.query(MenuItem).get(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    if body.group_id is not None:
        g = db.query(MenuGroup).get(body.group_id)
        if not g:
            raise HTTPException(404, "Target group not found")
        dup = (
            db.query(MenuItem)
            .filter(MenuItem.group_id == body.group_id, MenuItem.tab_key == item.tab_key, MenuItem.id != item.id)
            .first()
        )
        if dup:
            raise HTTPException(409, f"Tab '{item.tab_key}' already in target group")
        item.group_id = body.group_id
    if body.sort_order is not None:
        item.sort_order = body.sort_order
    db.commit()
    db.refresh(item)
    return _item_dict(item)


# ── DELETE /menu/items/{id} ─────────────────────────────────────────────────

@router.delete("/items/{item_id}", dependencies=[Depends(require_permission("menu.manage"))])
def delete_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(MenuItem).get(item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


# ── GET /menu/tabs ──────────────────────────────────────────────────────────

@router.get("/tabs")
def list_tabs():
    return {"tabs": [{"key": k, **v} for k, v in TAB_REGISTRY.items()]}