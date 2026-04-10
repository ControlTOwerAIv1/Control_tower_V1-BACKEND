"""
models.py
==========
SQLAlchemy 2.0 ORM models mapping to the existing KOL Distributor Toys
MySQL database tables.

These models are READ-ONLY. No schema changes, no migrations, no new tables.

SCHEMA CORRECTION (confirmed against live DB):
    - sales_bill and sales_bill_details are EMPTY - not used
    - Real sales data is in: invoice + invoice_details
    - invoice.invoice_date (datetime) is the sale date
    - invoice_details.invoice_id is the FK to invoice.id
    - invoice_details.product_id is the product FK
    - invoice_details.quantity (int) is units sold
    - lead_time_setting.days is VARCHAR, no product_id (global setting)
    - Product PK is id (not product_id)
"""

import datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Double, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


# ---------------------------------------------------------------------------
# 1. Product
# ---------------------------------------------------------------------------

class Product(Base):
    __tablename__ = "product"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    SKU: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    full_carton_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    loose_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    supplier_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    category_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<Product(id={self.id}, name='{self.name}', SKU='{self.SKU}')>"


# ---------------------------------------------------------------------------
# 2. WarehouseProductManagement
# ---------------------------------------------------------------------------

class WarehouseProductManagement(Base):
    __tablename__ = "warehouse_product_management"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    warehouse_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    product_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    threshold_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    advanced_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    carton: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<WarehouseProductManagement(id={self.id}, product_id={self.product_id}, qty={self.quantity})>"


# ---------------------------------------------------------------------------
# 3. Invoice  (replaces SalesBill — sales_bill table is empty)
# ---------------------------------------------------------------------------

class Invoice(Base):
    """
    ORM model for the `invoice` table.

    This is the real sales header table. invoice_date (datetime) is the
    sale date used for all date-based calculations.
    """
    __tablename__ = "invoice"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    customer_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sale_executive_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    invoice_date: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    activation_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payment_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    company_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<Invoice(id={self.id}, date={self.invoice_date}, total={self.total_amount})>"


# ---------------------------------------------------------------------------
# 4. InvoiceDetails  (replaces SalesBillDetails — sales_bill_details is empty)
# ---------------------------------------------------------------------------

class InvoiceDetails(Base):
    """
    ORM model for the `invoice_details` table.

    This is the real sales line-item table.
    - invoice_id: FK to invoice.id
    - product_id: FK to product.id
    - quantity: units sold (INT)
    No date column here — join to invoice via invoice_id for the date.
    """
    __tablename__ = "invoice_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    serial_no: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    invoice_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    product_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    carton: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sold_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<InvoiceDetails(id={self.id}, product_id={self.product_id}, qty={self.quantity})>"


# ---------------------------------------------------------------------------
# 5. LeadTimeSetting
# ---------------------------------------------------------------------------

class LeadTimeSetting(Base):
    """
    Global lead time setting. No product_id. days is VARCHAR.
    Most recent row (highest id) is the active setting.
    """
    __tablename__ = "lead_time_setting"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    days: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<LeadTimeSetting(id={self.id}, days='{self.days}')>"