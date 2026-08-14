from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from uuid import UUID
from app.database import get_db
from app.models import Supplier
from app.schemas import SupplierCreate, SupplierUpdate, SupplierResponse, PaginatedResponse

router = APIRouter(prefix="/api/suppliers", tags=["suppliers"])


@router.get("", response_model=PaginatedResponse)
def list_suppliers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = "",
    category: str = "",
    db: Session = Depends(get_db),
):
    query = db.query(Supplier)

    if search:
        query = query.filter(
            Supplier.supplier_name.ilike(f"%{search}%")
            | Supplier.supplier_id.ilike(f"%{search}%")
            | Supplier.origin_country.ilike(f"%{search}%")
        )
    if category:
        query = query.filter(Supplier.primary_category == category)

    total = query.count()
    items = query.order_by(Supplier.supplier_name).offset((page - 1) * page_size).limit(page_size).all()

    return PaginatedResponse(
        items=[SupplierResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/{supplier_id}", response_model=SupplierResponse)
def get_supplier(supplier_id: UUID, db: Session = Depends(get_db)):
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return SupplierResponse.model_validate(supplier)


@router.post("", response_model=SupplierResponse, status_code=201)
def create_supplier(data: SupplierCreate, db: Session = Depends(get_db)):
    existing = db.query(Supplier).filter(Supplier.supplier_id == data.supplier_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Supplier ID already exists")
    supplier = Supplier(**data.model_dump())
    db.add(supplier)
    db.commit()
    db.refresh(supplier)
    return SupplierResponse.model_validate(supplier)


@router.put("/{supplier_id}", response_model=SupplierResponse)
def update_supplier(supplier_id: UUID, data: SupplierUpdate, db: Session = Depends(get_db)):
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(supplier, key, value)
    db.commit()
    db.refresh(supplier)
    return SupplierResponse.model_validate(supplier)


@router.delete("/{supplier_id}")
def delete_supplier(supplier_id: UUID, db: Session = Depends(get_db)):
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    db.delete(supplier)
    db.commit()
    return {"detail": "Supplier deleted"}
