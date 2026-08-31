from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text as sql_text
from uuid import UUID
from datetime import date
from typing import Optional
from app.database import get_db
from app.models import Order, OrderItem, Product
from app.schemas import OrderCreate, OrderUpdate, OrderResponse, OrderItemResponse, PaginatedResponse
from app.routers.auth import get_current_user
from app.services.sap_connector import SAP_MOCK_URL
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("", response_model=PaginatedResponse)
def list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = "",
    payment_status: str = "",
    order_status: str = "",
    order_type: str = "",
    db: Session = Depends(get_db),
):
    try:
        query = db.query(Order).options(joinedload(Order.items))

        if search:
            query = query.filter(
                Order.order_id.ilike(f"%{search}%")
                | Order.customer_name.ilike(f"%{search}%")
                | Order.supplier_name.ilike(f"%{search}%")
                | Order.sap_po_number.ilike(f"%{search}%")
            )
        if payment_status:
            query = query.filter(Order.payment_status == payment_status)
        if order_status:
            query = query.filter(Order.order_status == order_status)
        if order_type:
            query = query.filter(Order.order_type == order_type)

        total = query.count()
        items = query.order_by(Order.order_date.desc()).offset((page - 1) * page_size).limit(page_size).all()

        return PaginatedResponse(
            items=[OrderResponse.model_validate(i) for i in items],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=(total + page_size - 1) // page_size,
        )
    except Exception as e:
        logger.error(f"Failed to fetch orders: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to fetch orders: {str(e)}")


@router.get("/sap-orders")
def list_sap_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    order_type: str = "",
    order_status: str = "",
    search: str = "",
    db: Session = Depends(get_db),
):
    """List SAP-synced orders (both Purchase Orders and Sales Orders) with line items."""
    try:
        query = db.query(Order).options(joinedload(Order.items)).filter(
            Order.sap_po_number.isnot(None)
        )

        if order_type:
            query = query.filter(Order.order_type == order_type)
        if order_status:
            query = query.filter(Order.order_status == order_status)
        if search:
            query = query.filter(
                Order.order_id.ilike(f"%{search}%")
                | Order.customer_name.ilike(f"%{search}%")
                | Order.supplier_name.ilike(f"%{search}%")
            )

        total = query.count()
        orders = query.order_by(Order.order_date.desc()).offset((page - 1) * page_size).limit(page_size).all()

        results = []
        for o in orders:
            product_ids = [it.product_id for it in o.items]
            products = {}
            if product_ids:
                for p in db.query(Product).filter(Product.id.in_(product_ids)).all():
                    products[str(p.id)] = {"sku_id": p.sku_id, "category": p.category}

            items_with_sku = []
            for it in o.items:
                prod_info = products.get(str(it.product_id), {})
                items_with_sku.append({
                    "id": str(it.id),
                    "sku_id": prod_info.get("sku_id", ""),
                    "category": prod_info.get("category", ""),
                    "quantity": it.quantity,
                    "unit_price_inr": it.unit_price_inr,
                    "total_price_inr": it.total_price_inr,
                })

            results.append({
                "id": str(o.id),
                "order_id": o.order_id,
                "order_date": o.order_date.isoformat() if o.order_date else None,
                "customer_name": o.customer_name,
                "supplier_name": o.supplier_name,
                "order_type": o.order_type,
                "total_amount_inr": o.total_amount_inr,
                "payment_status": o.payment_status,
                "order_status": o.order_status,
                "sap_po_number": o.sap_po_number,
                "fulfillment_region": o.fulfillment_region,
                "items": items_with_sku,
                "item_count": len(items_with_sku),
                "created_at": o.created_at.isoformat() if o.created_at else None,
            })

        return {
            "items": results,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }
    except Exception as e:
        logger.error(f"Failed to fetch SAP orders: {e}", exc_info=True)
        db.rollback()
        return {
            "items": [],
            "total": 0,
            "page": page,
            "page_size": page_size,
            "total_pages": 0,
        }


@router.get("/stock-movements")
def get_stock_movements(
    limit: int = Query(200, ge=1, le=1000),
):
    """Fetch stock movements (IN/OUT) from the SAP mock ERP."""
    import httpx
    try:
        response = httpx.get(f"{SAP_MOCK_URL}/sap/api/stock-movements",
                             params={"limit": limit}, timeout=30)
        if response.status_code == 200:
            data = response.json()
            movements = data.get("movements", [])

            enriched = []
            for m in movements:
                enriched.append({
                    "id": m.get("id", ""),
                    "matnr": m.get("MATNR", ""),
                    "quantity": m.get("quantity", 0),
                    "direction": m.get("direction", ""),
                    "movement_type": m.get("movement_type", ""),
                    "order_id": m.get("order_id", ""),
                    "order_date": m.get("order_date", ""),
                    "stock_after": m.get("stock_after", 0),
                    "timestamp": m.get("timestamp", ""),
                })
            return {"movements": enriched, "total": len(enriched)}
    except Exception:
        pass
    return {"movements": [], "total": 0}


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(order_id: UUID, db: Session = Depends(get_db)):
    order = db.query(Order).options(joinedload(Order.items)).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return OrderResponse.model_validate(order)


@router.get("/{order_id}/items")
def get_order_items(order_id: UUID, db: Session = Depends(get_db)):
    """Get full order detail: header + all line items with SKU info."""
    order = db.query(Order).options(joinedload(Order.items)).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    product_ids = [it.product_id for it in order.items]
    products = {}
    if product_ids:
        for p in db.query(Product).filter(Product.id.in_(product_ids)).all():
            products[str(p.id)] = {
                "sku_id": p.sku_id,
                "category": p.category,
                "sub_category": p.sub_category,
            }

    items = []
    for it in order.items:
        prod = products.get(str(it.product_id), {})
        items.append({
            "id": str(it.id),
            "sku_id": prod.get("sku_id", ""),
            "category": prod.get("category", ""),
            "sub_category": prod.get("sub_category", ""),
            "quantity": it.quantity,
            "unit_price_inr": it.unit_price_inr,
            "total_price_inr": it.total_price_inr,
        })

    return {
        "order": {
            "id": str(order.id),
            "order_id": order.order_id,
            "order_date": order.order_date.isoformat() if order.order_date else None,
            "customer_name": order.customer_name,
            "supplier_name": order.supplier_name,
            "order_type": order.order_type,
            "total_amount_inr": order.total_amount_inr,
            "payment_status": order.payment_status,
            "order_status": order.order_status,
            "sap_po_number": order.sap_po_number,
            "fulfillment_region": order.fulfillment_region,
            "created_at": order.created_at.isoformat() if order.created_at else None,
        },
        "items": items,
        "total_items": len(items),
    }


@router.post("", response_model=OrderResponse, status_code=201)
def create_order(data: OrderCreate, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    existing = db.query(Order).filter(Order.order_id == data.order_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Order ID already exists")

    order_data = data.model_dump(exclude={"items"})
    order = Order(**order_data)
    db.add(order)
    db.flush()

    for item_data in data.items:
        item = OrderItem(
            order_id=order.id,
            product_id=item_data.product_id,
            quantity=item_data.quantity,
            unit_price_inr=item_data.unit_price_inr,
            total_price_inr=item_data.quantity * item_data.unit_price_inr,
        )
        db.add(item)

    db.commit()
    db.refresh(order)
    return OrderResponse.model_validate(order)


@router.put("/{order_id}", response_model=OrderResponse)
def update_order(order_id: UUID, data: OrderUpdate, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(order, key, value)
    db.commit()
    db.refresh(order)
    return OrderResponse.model_validate(order)


@router.delete("/{order_id}")
def delete_order(order_id: UUID, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    db.delete(order)
    db.commit()
    return {"detail": "Order deleted"}
