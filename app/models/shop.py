import datetime

from sqlalchemy import (
    Column, String, Integer, Boolean, ForeignKey, Numeric, DateTime, Text, BigInteger, JSON, UniqueConstraint,
)

from app.db.base_class import Base


class Product(Base):
    """Shop product. Managed directly in SQL for now (see scripts/shop_products.sql)."""
    __tablename__ = "shop_products"

    id = Column(BigInteger, primary_key=True, index=True)
    vendor_id = Column(BigInteger, ForeignKey("vendors.id"), index=True, nullable=True)  # NULL = sold by AM5
    name = Column(String, nullable=False)
    short_description = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    category = Column(String(50), index=True, nullable=False, default="general")
    unit_label = Column(String(30), nullable=False, default="piece")
    price = Column(Numeric(10, 2), nullable=False)
    mrp = Column(Numeric(10, 2), nullable=True)
    stock_quantity = Column(Integer, nullable=False, default=0)
    images = Column(JSON, default=list)  # list of image URLs, first one is the main image
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class CartItem(Base):
    __tablename__ = "shop_cart_items"
    __table_args__ = (UniqueConstraint("customer_id", "product_id", name="uq_cart_customer_product"),)

    id = Column(BigInteger, primary_key=True, index=True)
    customer_id = Column(BigInteger, ForeignKey("customers.id"), index=True, nullable=False)
    product_id = Column(BigInteger, ForeignKey("shop_products.id"), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class ShopOrder(Base):
    __tablename__ = "shop_orders"

    id = Column(BigInteger, primary_key=True, index=True)
    order_number = Column(String(30), unique=True, index=True, nullable=True)
    customer_id = Column(BigInteger, ForeignKey("customers.id"), index=True, nullable=False)
    address_id = Column(BigInteger, nullable=True)
    delivery_address = Column(Text, nullable=True)  # copy of the address at order time
    subtotal_amount = Column(Numeric(10, 2), nullable=False)
    wallet_amount = Column(Numeric(10, 2), nullable=False, default=0)
    total_amount = Column(Numeric(10, 2), nullable=False)
    status = Column(String(20), nullable=False, default="placed")  # placed | confirmed | shipped | delivered | cancelled
    payment_status = Column(String(20), nullable=False, default="cod")  # cod (pay on delivery)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)


class ShopOrderItem(Base):
    __tablename__ = "shop_order_items"

    id = Column(BigInteger, primary_key=True, index=True)
    order_id = Column(BigInteger, ForeignKey("shop_orders.id"), index=True, nullable=False)
    product_id = Column(BigInteger, nullable=True)
    vendor_id = Column(BigInteger, nullable=True)
    product_name = Column(String, nullable=False)  # copied, so the order survives product edits
    unit_price = Column(Numeric(10, 2), nullable=False)
    quantity = Column(Integer, nullable=False)
    line_total = Column(Numeric(10, 2), nullable=False)
