from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from datetime import datetime, date
from typing import Optional, Literal


class ProductBase(BaseModel):
    sku_id: str
    category: str
    sub_category: Optional[str] = None
    machine_compatibility: Optional[str] = None
    shelf_life_days: Optional[int] = None
    unit_volume_m3: Optional[float] = None
    criticality_score: Optional[float] = None
    sap_material_id: Optional[str] = None


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    category: Optional[str] = None
    sub_category: Optional[str] = None
    machine_compatibility: Optional[str] = None
    shelf_life_days: Optional[int] = None
    unit_volume_m3: Optional[float] = None
    criticality_score: Optional[float] = None
    sap_material_id: Optional[str] = None


class ProductResponse(ProductBase):
    id: UUID | str
    current_stock: Optional[int] = 0
    last_synced_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SupplierBase(BaseModel):
    supplier_id: str
    supplier_name: str
    origin_country: Optional[str] = None
    primary_category: Optional[str] = None
    base_lead_time_days: Optional[int] = None
    lead_time_volatility: Optional[float] = None
    moq: Optional[int] = None
    unit_cost_inr: Optional[float] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    sap_vendor_id: Optional[str] = None


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    supplier_name: Optional[str] = None
    origin_country: Optional[str] = None
    primary_category: Optional[str] = None
    base_lead_time_days: Optional[int] = None
    lead_time_volatility: Optional[float] = None
    moq: Optional[int] = None
    unit_cost_inr: Optional[float] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    sap_vendor_id: Optional[str] = None


class SupplierResponse(SupplierBase):
    id: UUID
    last_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    user_id: str
    name: str
    email: str
    password: str
    role: Literal["Admin", "Manager", "Cashier", "Viewer"] = "Viewer"


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[Literal["Admin", "Manager", "Cashier", "Viewer"]] = None
    status: Optional[Literal["Active", "Inactive", "Suspended"]] = None


class UserResponse(BaseModel):
    id: UUID
    user_id: str
    name: str
    email: str
    role: str
    status: str
    last_login: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrderItemBase(BaseModel):
    product_id: UUID
    quantity: int
    unit_price_inr: float


class OrderItemCreate(OrderItemBase):
    pass


class OrderItemResponse(OrderItemBase):
    id: UUID
    sku_id: Optional[str] = None
    total_price_inr: float

    model_config = {"from_attributes": True}


class OrderBase(BaseModel):
    order_id: str
    order_date: date
    customer_name: Optional[str] = None
    supplier_name: Optional[str] = None
    order_type: str = "SALES_ORDER"
    total_amount_inr: float
    payment_status: str
    order_status: str
    sap_po_number: Optional[str] = None
    fulfillment_region: Optional[str] = None


class OrderCreate(OrderBase):
    items: list[OrderItemCreate] = []


class OrderUpdate(BaseModel):
    customer_name: Optional[str] = None
    supplier_name: Optional[str] = None
    order_type: Optional[str] = None
    total_amount_inr: Optional[float] = None
    payment_status: Optional[str] = None
    order_status: Optional[str] = None
    sap_po_number: Optional[str] = None
    fulfillment_region: Optional[str] = None


class OrderResponse(OrderBase):
    id: UUID
    items: list[OrderItemResponse] = []
    last_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StockMovementResponse(BaseModel):
    id: str
    matnr: str
    quantity: int
    direction: str
    movement_type: str
    order_id: str
    order_date: str
    stock_after: int
    timestamp: str


class SaleBase(BaseModel):
    sale_date: date
    sku_id: str
    units_sold: int
    fulfillment_region: Optional[str] = None
    stockout_flag: bool = False


class SaleCreate(SaleBase):
    product_id: UUID


class SaleResponse(SaleBase):
    id: UUID
    product_id: UUID

    model_config = {"from_attributes": True}


class DashboardKPI(BaseModel):
    total_skus: int
    total_suppliers: int
    active_orders: int
    total_sales: float
    low_stock_count: int
    fill_rate: float
    total_inventory_value: float
    total_units_in_stock: int


class ChartData(BaseModel):
    labels: list[str]
    values: list[float]


class SapSyncRequest(BaseModel):
    sync_type: Literal["materials", "vendors", "stocks", "orders", "sales"]


class SapSyncResponse(BaseModel):
    status: str
    message: str
    records_synced: int


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    user_id: Optional[str] = None


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
    total_pages: int


class InventoryBase(BaseModel):
    sku_id: str
    quantity_on_hand: int = 0
    quantity_reserved: int = 0
    quantity_available: int = 0
    unit_cost_inr: Optional[float] = None


class InventoryCreate(InventoryBase):
    pass


class InventoryUpdate(BaseModel):
    quantity_on_hand: Optional[int] = None
    quantity_reserved: Optional[int] = None
    quantity_available: Optional[int] = None
    unit_cost_inr: Optional[float] = None
    last_sap_sync_at: Optional[datetime] = None


class InventoryResponse(InventoryBase):
    id: UUID
    last_sap_sync_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
