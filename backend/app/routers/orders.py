from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from uuid import UUID
from datetime import date
from app.database import get_db
from app.models import Order, OrderItem
from app.schemas import OrderCreate, OrderUpdate, OrderResponse, OrderItemResponse, PaginatedResponse

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("", response_model=PaginatedResponse)
def list_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = "",
    payment_status: str = "",
    order_status: str = "",
    db: Session = Depends(get_db),
):
    query = db.query(Order).options(joinedload(Order.items))

    if search:
        query = query.filter(
            Order.order_id.ilike(f"%{search}%")
            | Order.customer_name.ilike(f"%{search}%")
            | Order.sap_po_number.ilike(f"%{search}%")
        )
    if payment_status:
        query = query.filter(Order.payment_status == payment_status)
    if order_status:
        query = query.filter(Order.order_status == order_status)

    total = query.count()
    items = query.order_by(Order.order_date.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return PaginatedResponse(
        items=[OrderResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(order_id: UUID, db: Session = Depends(get_db)):
    order = db.query(Order).options(joinedload(Order.items)).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return OrderResponse.model_validate(order)


@router.post("", response_model=OrderResponse, status_code=201)
def create_order(data: OrderCreate, db: Session = Depends(get_db)):
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
def update_order(order_id: UUID, data: OrderUpdate, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(order, key, value)
    db.commit()
    db.refresh(order)
    return OrderResponse.model_validate(order)


@router.delete("/{order_id}")
def delete_order(order_id: UUID, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    db.delete(order)
    db.commit()
    return {"detail": "Order deleted"}
