import uuid
from datetime import datetime, date
from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, Date, Text,
    ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sku_id = Column(String(50), unique=True, nullable=False, index=True)
    category = Column(String(100), nullable=False)
    sub_category = Column(String(100))
    machine_compatibility = Column(String(200))
    shelf_life_days = Column(Integer)
    unit_volume_m3 = Column(Float)
    criticality_score = Column(Float)
    sap_material_id = Column(String(50), unique=True, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sales = relationship("Sale", back_populates="product")
    forecast = relationship("Forecast", back_populates="product")


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    supplier_id = Column(String(50), unique=True, nullable=False, index=True)
    supplier_name = Column(String(200), nullable=False)
    origin_country = Column(String(100))
    primary_category = Column(String(100))
    base_lead_time_days = Column(Integer)
    lead_time_volatility = Column(Float)
    moq = Column(Integer)
    unit_cost_inr = Column(Float)
    email = Column(String(200))
    phone = Column(String(50))
    address = Column(Text)
    sap_vendor_id = Column(String(50), unique=True, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    email = Column(String(200), unique=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    role = Column(String(50), nullable=False, default="Viewer")
    status = Column(String(20), nullable=False, default="Active")
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(String(50), unique=True, nullable=False, index=True)
    order_date = Column(Date, nullable=False)
    customer_name = Column(String(200))
    total_amount_inr = Column(Float, nullable=False)
    payment_status = Column(String(50), nullable=False)
    order_status = Column(String(50), nullable=False)
    sap_po_number = Column(String(50), unique=True, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price_inr = Column(Float, nullable=False)
    total_price_inr = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product")


class Sale(Base):
    __tablename__ = "sales"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sale_date = Column(Date, nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    sku_id = Column(String(50), nullable=False)
    units_sold = Column(Integer, nullable=False)
    fulfillment_region = Column(String(100))
    stockout_flag = Column(Boolean, default=False)

    product = relationship("Product", back_populates="sales")

    __table_args__ = (
        Index("ix_sales_date_product", "sale_date", "product_id"),
    )


class ExternalFactor(Base):
    __tablename__ = "external_factors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    factor_date = Column(Date, nullable=False, unique=True)
    monsoon_index = Column(Float)
    crop_sowing_season = Column(String(50))
    macro_economic_index = Column(Float)

    __table_args__ = (
        Index("ix_external_date", "factor_date"),
    )


class Forecast(Base):
    __tablename__ = "forecasts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id"), nullable=False)
    sku_id = Column(String(50), nullable=False)
    forecast_date = Column(Date, nullable=False)
    predicted_demand = Column(Float, nullable=False)
    actual_demand = Column(Float, nullable=True)
    model_version = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="forecast")

    __table_args__ = (
        Index("ix_forecast_product_date", "product_id", "forecast_date"),
    )


class SapSyncLog(Base):
    __tablename__ = "sap_sync_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sync_type = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)
    records_synced = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SapConfig(Base):
    __tablename__ = "sap_config"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host = Column(String(200))
    system_number = Column(String(10))
    client = Column(String(10))
    user = Column(String(100))
    password_encrypted = Column(String(500))
    language = Column(String(10), default="EN")
    is_active = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
