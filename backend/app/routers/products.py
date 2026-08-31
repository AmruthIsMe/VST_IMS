from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import UUID
from app.database import get_db
from app.models import Product, Inventory
from app.schemas import ProductCreate, ProductUpdate, ProductResponse, PaginatedResponse
from app.routers.auth import get_current_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/products", tags=["products"])


@router.get("", response_model=PaginatedResponse)
def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = "",
    category: str = "",
    sort_by: str = "sku_id",
    sort_order: str = "asc",
    db: Session = Depends(get_db),
):
    try:
        query = db.query(Product)

        if search:
            query = query.filter(
                Product.sku_id.ilike(f"%{search}%")
                | Product.category.ilike(f"%{search}%")
                | Product.sub_category.ilike(f"%{search}%")
            )
        if category:
            query = query.filter(Product.category == category)

        total = query.count()

        valid_sort_cols = {
            "sku_id": Product.sku_id,
            "category": Product.category,
            "sub_category": Product.sub_category,
            "machine_compatibility": Product.machine_compatibility,
            "shelf_life_days": Product.shelf_life_days,
            "unit_volume_m3": Product.unit_volume_m3,
            "criticality_score": Product.criticality_score,
            "created_at": Product.created_at,
        }
        sort_col = valid_sort_cols.get(sort_by, Product.sku_id)
        if sort_order == "desc":
            query = query.order_by(sort_col.desc())
        else:
            query = query.order_by(sort_col.asc())

        items = query.offset((page - 1) * page_size).limit(page_size).all()

        stock_map = {}
        try:
            sku_ids = [p.sku_id for p in items if p.sku_id]
            if sku_ids:
                inv_rows = db.query(Inventory.sku_id, Inventory.quantity_on_hand).filter(
                    Inventory.sku_id.in_(sku_ids)
                ).all()
                for sku_id, qty in inv_rows:
                    stock_map[sku_id] = qty or 0
        except Exception as e:
            logger.warning(f"Failed to fetch stock map for products: {e}")
            db.rollback()

        response_items = []
        for p in items:
            response_items.append({
                "id": str(p.id) if p.id else "",
                "sku_id": p.sku_id or "",
                "category": p.category or "",
                "sub_category": p.sub_category,
                "machine_compatibility": p.machine_compatibility,
                "shelf_life_days": p.shelf_life_days,
                "unit_volume_m3": p.unit_volume_m3,
                "criticality_score": p.criticality_score,
                "sap_material_id": p.sap_material_id,
                "current_stock": stock_map.get(p.sku_id, 0),
                "last_synced_at": p.last_synced_at,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            })

        return PaginatedResponse(
            items=response_items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size if page_size else 1,
        )
    except Exception as e:
        logger.error(f"Failed to fetch products: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to fetch products: {str(e)}")


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    cats = db.query(Product.category, func.count(Product.id)).group_by(Product.category).all()
    return [{"category": c, "count": n} for c, n in cats]


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(product_id: UUID, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return ProductResponse.model_validate(product)


@router.post("", response_model=ProductResponse, status_code=201)
def create_product(data: ProductCreate, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    existing = db.query(Product).filter(Product.sku_id == data.sku_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="SKU already exists")
    product = Product(**data.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return ProductResponse.model_validate(product)


@router.put("/{product_id}", response_model=ProductResponse)
def update_product(product_id: UUID, data: ProductUpdate, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(product, key, value)
    db.commit()
    db.refresh(product)
    return ProductResponse.model_validate(product)


@router.delete("/{product_id}")
def delete_product(product_id: UUID, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    db.delete(product)
    db.commit()
    return {"detail": "Product deleted"}
