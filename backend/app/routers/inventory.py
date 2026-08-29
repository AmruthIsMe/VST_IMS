from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import UUID
from app.database import get_db
from app.models import Inventory
from app.schemas import InventoryCreate, InventoryUpdate, InventoryResponse, PaginatedResponse
from app.routers.auth import get_current_user

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


@router.get("", response_model=PaginatedResponse)
def list_inventory(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = "",
    db: Session = Depends(get_db),
):
    query = db.query(Inventory)

    if search:
        query = query.filter(Inventory.sku_id.ilike(f"%{search}%"))

    total = query.count()
    items = query.order_by(Inventory.sku_id.asc()).offset((page - 1) * page_size).limit(page_size).all()

    return PaginatedResponse(
        items=[InventoryResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/stock-map")
def get_stock_map(sku_ids: str = Query(None, description="Comma-separated SKU IDs"), db: Session = Depends(get_db)):
    """Return a lightweight {sku_id: quantity_on_hand} map for quick lookups."""
    query = db.query(Inventory.sku_id, Inventory.quantity_on_hand, Inventory.quantity_reserved, Inventory.quantity_available)
    if sku_ids:
        id_list = [s.strip() for s in sku_ids.split(",") if s.strip()]
        query = query.filter(Inventory.sku_id.in_(id_list))
    rows = query.all()
    return {
        row.sku_id: {
            "quantity_on_hand": row.quantity_on_hand,
            "quantity_reserved": row.quantity_reserved,
            "quantity_available": row.quantity_available,
        }
        for row in rows
    }


@router.get("/{inventory_id}", response_model=InventoryResponse)
def get_inventory(inventory_id: UUID, db: Session = Depends(get_db)):
    item = db.query(Inventory).filter(Inventory.id == inventory_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory record not found")
    return InventoryResponse.model_validate(item)


@router.post("", response_model=InventoryResponse, status_code=201)
def create_inventory(data: InventoryCreate, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    existing = db.query(Inventory).filter(Inventory.sku_id == data.sku_id).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Inventory record already exists for SKU {data.sku_id}")
    item = Inventory(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return InventoryResponse.model_validate(item)


@router.put("/{inventory_id}", response_model=InventoryResponse)
def update_inventory(inventory_id: UUID, data: InventoryUpdate, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    item = db.query(Inventory).filter(Inventory.id == inventory_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory record not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return InventoryResponse.model_validate(item)


@router.delete("/{inventory_id}")
def delete_inventory(inventory_id: UUID, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    item = db.query(Inventory).filter(Inventory.id == inventory_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory record not found")
    db.delete(item)
    db.commit()
    return {"detail": "Inventory record deleted"}
