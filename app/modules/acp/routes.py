from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.modules.a2a.discovery import merchant_registry
from app.modules.watch.objective import objective_store

acp_router = APIRouter(prefix='/acp/v1', tags=['Agentic Commerce Protocol (ACP) - Merchant Events'])


class InventoryUpdateRequest(BaseModel):
    sku: str = Field(..., description='Product variant SKU, e.g. adidas-runfalcon-3_blue_10')
    stock: int = Field(..., ge=0, description='New available inventory count')


class PriceUpdateRequest(BaseModel):
    sku: str = Field(..., description='Product variant SKU, e.g. adidas-runfalcon-3_blue_10')
    price: float = Field(..., gt=0, description='New base price in INR')


@acp_router.get('/merchants')
def list_merchants():
    '''Lists all registered A2A / ACP merchants with their IDs, names, and current catalog counts.'''
    merchants = merchant_registry.list_merchants()
    return [
        {
            'merchant_id': m.merchant_id,
            'merchant_name': m.merchant_name,
            'total_items': len(m.inventory),
            'currency': getattr(m, 'currency', 'INR'),
            'base_url': getattr(m, 'base_url', None),
        }
        for m in merchants
    ]


@acp_router.get('/merchants/{merchant_id}/inventory')
def get_merchant_inventory(merchant_id: str):
    '''Returns live inventory and stock levels for a registered merchant.'''
    m = merchant_registry.get_merchant(merchant_id)
    if not m:
        raise HTTPException(status_code=404, detail=f'Merchant {merchant_id} not found')
    m.reload_from_disk()
    return {
        'merchant_id': m.merchant_id,
        'merchant_name': m.merchant_name,
        'items': [it.model_dump() for it in m.inventory.values()],
    }


@acp_router.post('/merchants/{merchant_id}/inventory')
def update_merchant_inventory(merchant_id: str, req: InventoryUpdateRequest):
    '''ACP Merchant Inventory Webhook: Updates variant stock level and dispatches INVENTORY_CHANGED event to wake up active WATCHING objectives.'''
    m = merchant_registry.get_merchant(merchant_id)
    if not m:
        raise HTTPException(status_code=404, detail=f'Merchant {merchant_id} not found')
    updated = m.set_stock(req.sku, req.stock)
    if not updated:
        raise HTTPException(status_code=404, detail=f'SKU {req.sku} not found at {m.merchant_name}')
    return {
        'success': True,
        'event': 'INVENTORY_CHANGED',
        'merchant_id': m.merchant_id,
        'merchant_name': m.merchant_name,
        'sku': req.sku,
        'new_stock': req.stock,
        'message': f'Successfully updated stock to {req.stock} and dispatched INVENTORY_CHANGED event.',
    }


@acp_router.post('/merchants/{merchant_id}/price')
def update_merchant_price(merchant_id: str, req: PriceUpdateRequest):
    '''ACP Merchant Price Webhook: Updates variant price and dispatches PRICE_CHANGED event.'''
    m = merchant_registry.get_merchant(merchant_id)
    if not m:
        raise HTTPException(status_code=404, detail=f'Merchant {merchant_id} not found')
    updated = m.set_price(req.sku, req.price)
    if not updated:
        raise HTTPException(status_code=404, detail=f'SKU {req.sku} not found at {m.merchant_name}')
    return {
        'success': True,
        'event': 'PRICE_CHANGED',
        'merchant_id': m.merchant_id,
        'merchant_name': m.merchant_name,
        'sku': req.sku,
        'new_price': req.price,
        'message': f'Successfully updated price to Rs. {req.price:,-.2f} and dispatched PRICE_CHANGED event.',
    }


@acp_router.get('/objectives')
def list_shopping_objectives():
    '''Lists all active and historical autonomous shopping objectives and their current state (WATCHING, COMPLETED, etc.).'''
    objs = objective_store.get_all_objectives()
    return [
        {
            'objective_id': o.objective_id,
            'status': o.status,
            'query': o.user_intent.get('query'),
            'max_price': o.user_intent.get('max_price'),
            'watch_reason': o.watch_reason,
            'purchase_result': o.purchase_result,
        }
        for o in objs
    ]
