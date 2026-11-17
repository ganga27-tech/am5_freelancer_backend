"""Shop: products, cart and product orders (mounted at the API root). COD only."""
import datetime as dt
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, delete, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.db.session import get_db
from app.dependencies.auth import get_current_customer
from app.models.shop import Product, CartItem, ShopOrder, ShopOrderItem
from app.models.user_location import Customer, Address as AddressModel
from app.models.vendor import Vendor
from app.services import customer_wallet_service as wallets
from app.services.customer_wallet_service import money

router = APIRouter()


def _iso(value: Optional[dt.datetime]) -> Optional[str]:
    return value.isoformat() + "Z" if value else None


# ------------------------------------------------------------------ products

async def _vendor_names(db: AsyncSession, products: List[Product]) -> Dict[int, str]:
    ids = {p.vendor_id for p in products if p.vendor_id}
    if not ids:
        return {}
    rows = await db.execute(select(Vendor.id, Vendor.business_name).where(Vendor.id.in_(ids)))
    return {vid: name or "Vendor" for vid, name in rows.all()}


def _product_json(p: Product, vendor_names: Dict[int, str]) -> dict:
    images = list(p.images or [])
    return {
        "id": str(p.id),
        "professional_id": str(p.vendor_id or 0),
        "vendor_name": vendor_names.get(p.vendor_id) if p.vendor_id else "AM5 Royal",
        "name": p.name,
        "slug": str(p.id),
        "short_description": p.short_description,
        "description": p.description,
        "category": p.category,
        "image_url": images[0] if images else None,
        "images": images,
        "price_amount": float(p.price),
        "mrp": float(p.mrp) if p.mrp is not None else None,
        "currency": "INR",
        "stock_quantity": int(p.stock_quantity or 0),
        "unit_label": p.unit_label,
        "is_active": bool(p.is_active),
        "status": "approved",
    }


async def _products_json(db: AsyncSession, products: List[Product]) -> List[dict]:
    names = await _vendor_names(db, products)
    return [_product_json(p, names) for p in products]


@router.get("/products")
@limiter.limit("60/minute")
async def list_products(
    request: Request,
    category: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Search in name and description"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    query = select(Product).where(Product.is_active == True)
    if category and category.strip():
        query = query.where(func.lower(Product.category) == category.strip().lower())
    if q and q.strip():
        term = q.strip().replace("%", r"\%").replace("_", r"\_")
        like = f"%{term}%"
        query = query.where(
            Product.name.ilike(like, escape="\\")
            | Product.short_description.ilike(like, escape="\\")
            | Product.description.ilike(like, escape="\\")
        )
    products = (await db.execute(query.order_by(Product.id).offset(offset).limit(limit))).scalars().all()
    return await _products_json(db, products)


@router.get("/products/{product_id}")
@limiter.limit("60/minute")
async def get_product(
    request: Request,
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    product = await db.get(Product, product_id)
    if not product or not product.is_active:
        raise HTTPException(status_code=404, detail="Product not found")
    return (await _products_json(db, [product]))[0]


@router.get("/vendors/{vendor_id}/products")
@limiter.limit("60/minute")
async def list_vendor_products(
    request: Request,
    vendor_id: int,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """Products sold by one vendor. Empty list if the vendor sells none."""
    products = (await db.execute(
        select(Product)
        .where(Product.vendor_id == vendor_id, Product.is_active == True)
        .order_by(Product.id).offset(offset).limit(limit)
    )).scalars().all()
    return await _products_json(db, products)


# ---------------------------------------------------------------------- cart

async def _cart_json(db: AsyncSession, customer_id: int) -> dict:
    rows = (await db.execute(
        select(CartItem, Product)
        .join(Product, Product.id == CartItem.product_id)
        .where(CartItem.customer_id == customer_id, Product.is_active == True)
        .order_by(CartItem.id)
    )).all()
    names = await _vendor_names(db, [p for _, p in rows])
    items, subtotal, count = [], money(0), 0
    for item, product in rows:
        items.append({
            "product_id": str(product.id),
            "quantity": item.quantity,
            "product": _product_json(product, names),
        })
        subtotal += money(product.price) * item.quantity
        count += item.quantity
    return {
        "id": f"cart-{customer_id}",
        "items": items,
        "item_count": count,
        "subtotal_amount": float(subtotal),
        "currency": "INR",
    }


@router.get("/cart")
@limiter.limit("60/minute")
async def get_cart(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    return await _cart_json(db, current_customer.id)


class CartItemRequest(BaseModel):
    product_id: int
    quantity: int = Field(..., ge=0, le=99)  # 0 removes the line


@router.put("/cart/items")
@limiter.limit("60/minute")
async def put_cart_item(
    request: Request,
    body: CartItemRequest,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """Add a product, or set its quantity. Quantity 0 removes it."""
    existing_q = select(CartItem).where(
        CartItem.customer_id == current_customer.id, CartItem.product_id == body.product_id)

    if body.quantity == 0:
        await db.execute(delete(CartItem).where(
            CartItem.customer_id == current_customer.id, CartItem.product_id == body.product_id))
        await db.commit()
        return await _cart_json(db, current_customer.id)

    product = await db.get(Product, body.product_id)
    if not product or not product.is_active:
        raise HTTPException(status_code=404, detail="Product not found")
    stock = int(product.stock_quantity or 0)
    if stock <= 0:
        raise HTTPException(status_code=400, detail=f"'{product.name}' is out of stock")
    if body.quantity > stock:
        raise HTTPException(status_code=400, detail=f"Only {stock} of '{product.name}' left")

    item = (await db.execute(existing_q)).scalar_one_or_none()
    if item:
        item.quantity = body.quantity
    else:
        db.add(CartItem(customer_id=current_customer.id, product_id=body.product_id, quantity=body.quantity))
    try:
        await db.commit()
    except IntegrityError:  # two adds raced: update the row the other request created
        await db.rollback()
        item = (await db.execute(existing_q)).scalar_one_or_none()
        if item:
            item.quantity = body.quantity
            await db.commit()
    return await _cart_json(db, current_customer.id)


@router.delete("/cart/items/{product_id}")
@limiter.limit("60/minute")
async def delete_cart_item(
    request: Request,
    product_id: int,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    await db.execute(delete(CartItem).where(
        CartItem.customer_id == current_customer.id, CartItem.product_id == product_id))
    await db.commit()
    return await _cart_json(db, current_customer.id)


# -------------------------------------------------------------------- orders

def _order_json(order: ShopOrder, items: List[ShopOrderItem]) -> dict:
    return {
        "id": order.order_number,
        "status": order.status,
        "payment_status": order.payment_status,
        "subtotal_amount": float(order.subtotal_amount),
        "wallet_amount": float(order.wallet_amount),
        "gateway_amount": 0.0,
        "total_amount": float(order.total_amount),
        "amount_due": float(money(order.total_amount) - money(order.wallet_amount)),
        "currency": "INR",
        "paid_at": None,
        "delivery_address_snapshot": order.delivery_address,
        "created_at": _iso(order.created_at),
        "items": [
            {
                "id": str(i.id),
                "product_id": str(i.product_id) if i.product_id else None,
                "professional_id": str(i.vendor_id) if i.vendor_id else None,
                "product_name": i.product_name,
                "unit_price": float(i.unit_price),
                "quantity": i.quantity,
                "line_total": float(i.line_total),
            }
            for i in items
        ],
    }


class ShopOrderCreate(BaseModel):
    address_id: int
    use_wallet_amount: float = Field(0, ge=0)


@router.post("/shop/orders")
@limiter.limit("5/minute")
async def create_shop_order(
    request: Request,
    body: ShopOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """
    Turn the cart into an order (pay on delivery, optionally part-paid from the wallet).
    Prices and stock come from the database at this moment, not from the cart or the client.
    """
    address = (await db.execute(
        select(AddressModel).where(
            AddressModel.id == body.address_id,
            AddressModel.customer_id == current_customer.id,
            AddressModel.deleted == False,
        )
    )).scalar_one_or_none()
    if not address:
        raise HTTPException(status_code=400, detail="Invalid address_id or address does not belong to customer")

    cart = (await db.execute(
        select(CartItem).where(CartItem.customer_id == current_customer.id).order_by(CartItem.product_id)
    )).scalars().all()
    if not cart:
        raise HTTPException(status_code=400, detail="Your cart is empty")

    # Lock the products in id order (no deadlocks) so concurrent orders cannot oversell.
    products = {
        p.id: p for p in (await db.execute(
            select(Product).where(Product.id.in_([c.product_id for c in cart])).order_by(Product.id).with_for_update()
        )).scalars().all()
    }

    lines, subtotal = [], money(0)
    for item in cart:
        product = products.get(item.product_id)
        if not product or not product.is_active:
            raise HTTPException(status_code=409, detail="An item in your cart is no longer available")
        if int(product.stock_quantity or 0) < item.quantity:
            left = int(product.stock_quantity or 0)
            raise HTTPException(
                status_code=409,
                detail=f"Only {left} of '{product.name}' left" if left else f"'{product.name}' is out of stock",
            )
        line_total = money(product.price) * item.quantity
        subtotal += line_total
        lines.append((item, product, line_total))

    wallet_amount = money(body.use_wallet_amount)
    if wallet_amount > subtotal:
        raise HTTPException(status_code=400, detail="Wallet amount is more than the order total")

    parts = [address.address_line1, address.address_line2, address.city, address.state, address.pincode]
    order = ShopOrder(
        customer_id=current_customer.id, address_id=address.id,
        delivery_address=", ".join(p for p in parts if p),
        subtotal_amount=subtotal, wallet_amount=wallet_amount, total_amount=subtotal,
        status="placed", payment_status="cod",
    )
    db.add(order)
    await db.flush()
    order.order_number = f"SHP-{dt.datetime.utcnow().year}-{order.id:06d}"

    order_items = []
    for item, product, line_total in lines:
        product.stock_quantity = int(product.stock_quantity) - item.quantity
        row = ShopOrderItem(
            order_id=order.id, product_id=product.id, vendor_id=product.vendor_id,
            product_name=product.name, unit_price=money(product.price),
            quantity=item.quantity, line_total=line_total,
        )
        db.add(row)
        order_items.append(row)

    if wallet_amount > 0:
        try:
            await wallets.debit(
                db, current_customer.id, wallet_amount, "Used for shop order",
                reference=f"shop-order:{order.id}",
            )
        except wallets.InsufficientBalance:
            await db.rollback()
            raise HTTPException(status_code=400, detail="Insufficient wallet balance")

    await db.execute(delete(CartItem).where(CartItem.customer_id == current_customer.id))
    await db.commit()
    await db.refresh(order)
    for row in order_items:
        await db.refresh(row)
    return _order_json(order, order_items)


async def _items_by_order(db: AsyncSession, order_ids: List[int]) -> Dict[int, List[ShopOrderItem]]:
    grouped: Dict[int, List[ShopOrderItem]] = {oid: [] for oid in order_ids}
    if order_ids:
        rows = (await db.execute(
            select(ShopOrderItem).where(ShopOrderItem.order_id.in_(order_ids)).order_by(ShopOrderItem.id)
        )).scalars().all()
        for row in rows:
            grouped[row.order_id].append(row)
    return grouped


@router.get("/shop/orders")
@limiter.limit("30/minute")
async def list_shop_orders(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    """The customer's product orders, newest first. Empty list if none."""
    orders = (await db.execute(
        select(ShopOrder)
        .where(ShopOrder.customer_id == current_customer.id)
        .order_by(ShopOrder.created_at.desc(), ShopOrder.id.desc())
        .offset(skip).limit(limit)
    )).scalars().all()
    items = await _items_by_order(db, [o.id for o in orders])
    return [_order_json(o, items[o.id]) for o in orders]


@router.get("/shop/orders/{order_number}")
@limiter.limit("30/minute")
async def get_shop_order(
    request: Request,
    order_number: str,
    db: AsyncSession = Depends(get_db),
    current_customer: Customer = Depends(get_current_customer),
):
    order = (await db.execute(
        select(ShopOrder).where(
            ShopOrder.order_number == order_number, ShopOrder.customer_id == current_customer.id)
    )).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    items = await _items_by_order(db, [order.id])
    return _order_json(order, items[order.id])
