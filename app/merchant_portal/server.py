"""Merchant Portal & Autonomous Watch Control Server.

Provides a clean, minimalist web frontend and Swagger UI (/docs) to:
1. Inspect all 3 merchant stores (UrbanKicks, ShoeKart, FastFeet) and product catalogs.
2. Edit live stock and price with 1 click or direct input.
3. Monitor active autonomous shopping objectives (WATCHING -> EVALUATING -> COMPLETED).
4. Watch catalog.json file edits in real-time to trigger watch re-evaluations automatically.
"""

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.merchants import merchant_a, merchant_b, merchant_c
from app.modules.buyer.ledger import buyer_ledger
from app.modules.watch.event_bus import event_bus
from app.modules.watch.objective import objective_store
from app.shopping_agent.orchestrator import shopping_orchestrator

MERCHANTS = {
    "merchant_a": merchant_a,
    "urbankicks": merchant_a,
    "merchant_b": merchant_b,
    "shoekart": merchant_b,
    "merchant_c": merchant_c,
    "fastfeet": merchant_c,
}

# Catalog file tracking for background file-watcher
CATALOG_MTIMES: dict[str, float] = {}


async def _background_catalog_file_watcher():
    """Monitors merchant catalog.json files for external edits (e.g. VS Code / editor)."""
    global CATALOG_MTIMES
    catalog_paths = {
        "merchant_a": _ROOT / "merchants" / "merchant_a" / "catalog.json",
        "merchant_b": _ROOT / "merchants" / "merchant_b" / "catalog.json",
        "merchant_c": _ROOT / "merchants" / "merchant_c" / "catalog.json",
    }
    for m_id, path in catalog_paths.items():
        if path.exists():
            CATALOG_MTIMES[m_id] = path.stat().st_mtime

    while True:
        await asyncio.sleep(1.0)
        for m_id, path in catalog_paths.items():
            if not path.exists():
                continue
            curr_mtime = path.stat().st_mtime
            prev_mtime = CATALOG_MTIMES.get(m_id, curr_mtime)
            if curr_mtime > prev_mtime:
                CATALOG_MTIMES[m_id] = curr_mtime
                m = MERCHANTS.get(m_id)
                if m:
                    m.reload_from_disk()
                    # Trigger event bus to notify any watching objectives
                    event_bus.publish(
                        event_type="INVENTORY_CHANGED",
                        merchant_id=m_id,
                        payload={"source": "file_watcher", "catalog_path": str(path)},
                    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure orchestrator is listening to event bus
    watcher_task = asyncio.create_task(_background_catalog_file_watcher())
    yield
    watcher_task.cancel()


app = FastAPI(
    title="Razorpay Autonomous Commerce — Merchant Portal",
    description="Interactive control panel and Swagger API for managing merchant stock, prices, and simulating the autonomous WATCH re-evaluation flow.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StockUpdateRequest(BaseModel):
    sku: str
    stock: int


class PriceUpdateRequest(BaseModel):
    sku: str
    price: float


class TestObjectiveRequest(BaseModel):
    description: str = "Buy Adidas blue sneakers, size 10, under Rs. 4,600"
    query: str = "adidas"
    max_price: float = 4600.0
    size: int | None = 10
    color: str | None = "blue"


@app.get("/api/merchants")
def get_merchants():
    """Lists all active merchants and their flattened catalog items."""
    results = []
    for m_id in ["merchant_a", "merchant_b", "merchant_c"]:
        m = MERCHANTS[m_id]
        m.reload_from_disk()
        catalog_items = m.get_full_catalog()
        results.append({
            "id": m.merchant_id,
            "name": m.merchant_name,
            "currency": m.currency,
            "item_count": len(catalog_items),
            "items": catalog_items,
        })
    return results


@app.post("/api/merchants/{merchant_id}/stock")
def update_stock(merchant_id: str, req: StockUpdateRequest):
    """Updates stock for a product SKU and triggers an INVENTORY_CHANGED event."""
    m = MERCHANTS.get(merchant_id.lower())
    if not m:
        raise HTTPException(status_code=404, detail=f"Merchant '{merchant_id}' not found")

    item = m.set_stock(req.sku, req.stock)
    if not item:
        raise HTTPException(status_code=404, detail=f"SKU '{req.sku}' not found in {m.merchant_name} catalog")

    return {
        "success": True,
        "merchant": m.merchant_name,
        "sku": req.sku,
        "new_stock": req.stock,
        "message": f"Updated stock to {req.stock}. Event published to Event Bus.",
    }


@app.post("/api/merchants/{merchant_id}/price")
def update_price(merchant_id: str, req: PriceUpdateRequest):
    """Updates unit price for a product SKU and triggers a PRICE_CHANGED event."""
    m = MERCHANTS.get(merchant_id.lower())
    if not m:
        raise HTTPException(status_code=404, detail=f"Merchant '{merchant_id}' not found")

    item = m.set_price(req.sku, req.price)
    if not item:
        raise HTTPException(status_code=404, detail=f"SKU '{req.sku}' not found in {m.merchant_name} catalog")

    return {
        "success": True,
        "merchant": m.merchant_name,
        "sku": req.sku,
        "new_price": req.price,
        "message": f"Updated price to Rs. {req.price:,.2f}. Event published to Event Bus.",
    }


@app.get("/api/objectives")
def get_objectives():
    """Lists all active and historical shopping objectives."""
    objs = objective_store.get_all_objectives()
    return [
        {
            "objective_id": o.objective_id,
            "status": o.status.value,
            "user_intent": o.user_intent,
            "watch_reason": o.watch_reason,
            "created_at": o.created_at,
            "updated_at": o.updated_at,
            "purchase_result": o.purchase_result,
        }
        for o in objs
    ]


@app.post("/api/objectives/create-test")
def create_test_objective(req: TestObjectiveRequest):
    """Creates a sample shopping objective directly from the portal for demo testing."""
    intent = {
        "description": req.description,
        "query": req.query,
        "max_price": req.max_price,
        "size": req.size,
        "color": req.color,
        "quantity": 1,
        "auto_purchase": True,
    }
    result = shopping_orchestrator.execute_intent(intent=intent, enable_watching=True)
    return result


@app.post("/api/quick-action/{action_name}")
def execute_quick_action(action_name: str):
    """Executes preset demo triggers for effortless live demonstrations."""
    sku = "adidas-runfalcon-3_blue_10"
    m_shoekart = MERCHANTS["merchant_b"]

    if action_name == "set_out_of_stock":
        m_shoekart.set_stock(sku, 0)
        return {"action": action_name, "status": "ShoeKart Adidas blue size 10 set to 0 stock"}

    elif action_name == "restock_shoekart":
        m_shoekart.set_stock(sku, 4)
        return {"action": action_name, "status": "ShoeKart Adidas blue size 10 restocked to 4 units"}

    elif action_name == "price_drop_shoekart":
        m_shoekart.set_price(sku, 4100.0)
        return {"action": action_name, "status": "ShoeKart Adidas blue size 10 discounted to Rs. 4,100"}

    elif action_name == "reset_price_shoekart":
        m_shoekart.set_price(sku, 4549.0)
        return {"action": action_name, "status": "ShoeKart Adidas blue size 10 restored to standard Rs. 4,549"}

    elif action_name == "topup_buyer":
        buyer_ledger.record_credit(amount=5000.0, source="razorpay_smart_collect", notes="Portal demo top-up")
        event_bus.publish(event_type="BALANCE_CHANGED", payload={"new_balance": buyer_ledger.available_balance})
        return {"action": action_name, "status": f"Credited Rs. 5,000. New balance: Rs. {buyer_ledger.available_balance:,.2f}"}

    else:
        raise HTTPException(status_code=400, detail=f"Unknown quick action '{action_name}'")


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def get_dashboard_html():
    """Serves a modern, minimalist live merchant and watch monitoring dashboard."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Razorpay Autonomous Commerce — Merchant Portal & Live Watch</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    @keyframes pulse-subtle {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.6; }
    }
    .pulse-amber { animation: pulse-subtle 2s infinite; }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans antialiased">
  
  <!-- Header -->
  <header class="border-b border-slate-800 bg-slate-900/60 backdrop-blur sticky top-0 z-50">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div>
        <div class="flex items-center gap-3">
          <span class="w-3 h-3 rounded-full bg-emerald-500 animate-ping"></span>
          <h1 class="text-xl font-bold tracking-tight text-white">Razorpay Autonomous Commerce</h1>
          <span class="text-xs px-2.5 py-0.5 rounded-full bg-blue-500/20 text-blue-400 border border-blue-500/30">Merchant Portal</span>
        </div>
        <p class="text-xs text-slate-400 mt-1">Live Store Catalogs, Instant Restock/Price Controls, and Real-Time Watch Objectives</p>
      </div>
      
      <div class="flex items-center gap-3">
        <a href="/docs" target="_blank" class="text-xs px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition flex items-center gap-1.5">
          <svg class="w-3.5 h-3.5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"/></svg>
          Swagger API Docs
        </a>
        <a href="http://127.0.0.1:8000" target="_blank" class="text-xs px-3 py-1.5 rounded-md bg-blue-600 hover:bg-blue-500 text-white font-medium transition shadow-lg shadow-blue-600/20 flex items-center gap-1.5">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
          Open ADK Web UI
        </a>
      </div>
    </div>
  </header>

  <main class="max-w-7xl mx-auto px-4 sm:px-6 py-8 space-y-8">

    <!-- Demo Action Bar -->
    <section class="bg-slate-900/80 border border-slate-800 rounded-xl p-5">
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 class="text-sm font-semibold text-slate-200">1-Click Live Demo Triggers</h2>
          <p class="text-xs text-slate-400 mt-0.5">Simulate store events during your live presentation without touching a terminal.</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button onclick="runQuickAction('set_out_of_stock')" class="text-xs px-3 py-2 rounded-lg bg-rose-950/60 hover:bg-rose-900 text-rose-300 border border-rose-800 transition">
            1. Set ShoeKart Out-of-Stock (0)
          </button>
          <button onclick="runQuickAction('restock_shoekart')" class="text-xs px-3 py-2 rounded-lg bg-emerald-950/60 hover:bg-emerald-900 text-emerald-300 border border-emerald-800 transition font-medium">
            2. Restock ShoeKart (4 units)
          </button>
          <button onclick="runQuickAction('price_drop_shoekart')" class="text-xs px-3 py-2 rounded-lg bg-amber-950/60 hover:bg-amber-900 text-amber-300 border border-amber-800 transition">
            3. Flash Sale (Drop to Rs. 4,100)
          </button>
          <button onclick="runQuickAction('reset_price_shoekart')" class="text-xs px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition">
            Reset Price (Rs. 4,549)
          </button>
        </div>
      </div>
      <div id="action-feedback" class="text-xs text-emerald-400 font-mono mt-3 hidden"></div>
    </section>

    <!-- Section: Live Watch Objectives -->
    <section class="space-y-4">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <h2 class="text-base font-semibold text-slate-200">Live Shopping Objectives (WATCH Engine)</h2>
          <span id="obj-count-badge" class="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">0</span>
        </div>
        <button onclick="fetchObjectives()" class="text-xs text-slate-400 hover:text-slate-200 flex items-center gap-1">
          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
          Refresh
        </button>
      </div>

      <div id="objectives-container" class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="col-span-full py-8 text-center text-xs text-slate-500 border border-dashed border-slate-800 rounded-xl">
          Loading active shopping objectives...
        </div>
      </div>
    </section>

    <!-- Section: Merchant Stores -->
    <section class="space-y-4">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="text-base font-semibold text-slate-200">Merchant Store Catalogs & Controls</h2>
          <p class="text-xs text-slate-400">Edit inventory stock or unit prices directly. Changes automatically trigger the Watch Event Bus.</p>
        </div>
      </div>

      <div id="merchants-container" class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="col-span-full py-8 text-center text-xs text-slate-500 border border-dashed border-slate-800 rounded-xl">
          Loading merchant catalogs...
        </div>
      </div>
    </section>

  </main>

  <script>
    async function runQuickAction(action) {
      try {
        const res = await fetch(`/api/quick-action/${action}`, { method: 'POST' });
        const data = await res.json();
        const fb = document.getElementById('action-feedback');
        fb.innerText = `[OK] ${data.status}`;
        fb.classList.remove('hidden');
        setTimeout(() => fb.classList.add('hidden'), 4000);
        fetchMerchants();
        fetchObjectives();
      } catch (err) {
        alert('Action error: ' + err);
      }
    }

    async function updateItemStock(merchantId, sku, newStock) {
      try {
        const res = await fetch(`/api/merchants/${merchantId}/stock`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sku: sku, stock: parseInt(newStock) })
        });
        const data = await res.json();
        if (data.success) {
          fetchMerchants();
          fetchObjectives();
        } else {
          alert(data.detail || 'Stock update failed');
        }
      } catch (err) {
        alert('Error updating stock: ' + err);
      }
    }

    async function updateItemPrice(merchantId, sku, newPrice) {
      try {
        const res = await fetch(`/api/merchants/${merchantId}/price`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sku: sku, price: parseFloat(newPrice) })
        });
        const data = await res.json();
        if (data.success) {
          fetchMerchants();
          fetchObjectives();
        } else {
          alert(data.detail || 'Price update failed');
        }
      } catch (err) {
        alert('Error updating price: ' + err);
      }
    }

    async function fetchObjectives() {
      try {
        const res = await fetch('/api/objectives');
        const list = await res.json();
        document.getElementById('obj-count-badge').innerText = list.length;
        const container = document.getElementById('objectives-container');

        if (list.length === 0) {
          container.innerHTML = `
            <div class="col-span-full py-8 text-center text-xs text-slate-500 border border-dashed border-slate-800 rounded-xl">
              No shopping objectives active yet. Issue a request in ADK Web UI (e.g. "Buy Adidas blue sneakers under 4600") to see it appear here!
            </div>
          `;
          return;
        }

        container.innerHTML = list.map(obj => {
          let badge = '';
          if (obj.status === 'WATCHING') {
            badge = '<span class="text-xs px-2.5 py-1 rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30 pulse-amber font-medium">WATCHING</span>';
          } else if (obj.status === 'COMPLETED') {
            badge = '<span class="text-xs px-2.5 py-1 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 font-semibold">COMPLETED</span>';
          } else if (obj.status === 'EVALUATING') {
            badge = '<span class="text-xs px-2.5 py-1 rounded-full bg-blue-500/20 text-blue-400 border border-blue-500/30 font-medium">RE-EVALUATING</span>';
          } else {
            badge = `<span class="text-xs px-2.5 py-1 rounded-full bg-slate-800 text-slate-300 border border-slate-700">${obj.status}</span>`;
          }

          let resultBlock = '';
          if (obj.purchase_result && obj.purchase_result.success) {
            const pr = obj.purchase_result;
            resultBlock = `
              <div class="mt-3 pt-3 border-t border-slate-800 text-xs space-y-1">
                <div class="text-emerald-400 font-medium">Order Completed via Razorpay:</div>
                <div class="text-slate-300">Purchased <span class="text-white font-medium">${pr.item_purchased}</span> from <span class="text-white font-medium">${pr.merchant}</span></div>
                <div class="text-slate-400">Total Paid: <span class="text-white font-mono">Rs. ${pr.amount_paid_inr.toLocaleString()}</span> | Order: <code class="text-blue-400">${pr.order_id || 'N/A'}</code></div>
              </div>
            `;
          } else if (obj.watch_reason) {
            resultBlock = `
              <div class="mt-2 text-xs text-amber-400/80 font-mono">
                Reason: ${obj.watch_reason}
              </div>
            `;
          }

          return `
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
              <div class="flex items-center justify-between">
                <span class="text-xs text-slate-500 font-mono">${obj.objective_id}</span>
                ${badge}
              </div>
              <div class="text-sm font-medium text-slate-100">
                "${obj.user_intent.description || obj.user_intent.query}"
              </div>
              <div class="text-xs text-slate-400 flex gap-4">
                <span>Budget: <strong class="text-slate-200">Rs. ${obj.user_intent.max_price?.toLocaleString() || 'Any'}</strong></span>
                <span>Size: <strong class="text-slate-200">${obj.user_intent.size || 'Any'}</strong></span>
              </div>
              ${resultBlock}
            </div>
          `;
        }).join('');
      } catch (err) {
        console.error('Error fetching objectives:', err);
      }
    }

    async function fetchMerchants() {
      try {
        const res = await fetch('/api/merchants');
        const merchants = await res.json();
        const container = document.getElementById('merchants-container');

        container.innerHTML = merchants.map(m => {
          const itemsHtml = m.items.map(it => {
            const isOos = it.stock <= 0;
            const stockBadge = isOos
              ? '<span class="text-[10px] px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-400 border border-rose-500/30">OUT OF STOCK</span>'
              : `<span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">${it.stock} IN STOCK</span>`;

            return `
              <div class="bg-slate-950/60 border border-slate-800/80 rounded-lg p-3 space-y-2.5">
                <div class="flex items-start justify-between gap-2">
                  <div>
                    <div class="text-xs font-semibold text-slate-200">${it.name}</div>
                    <div class="text-[10px] text-slate-500 font-mono">${it.id}</div>
                  </div>
                  ${stockBadge}
                </div>

                <div class="text-xs text-slate-400 flex items-center justify-between">
                  <span>Size: ${it.attributes?.size || 'N/A'} | Color: ${it.attributes?.color || 'N/A'}</span>
                  <span class="text-[10px] text-slate-500">${it.attributes?.delivery?.standard_days || 3}-day deliv</span>
                </div>

                <!-- Controls -->
                <div class="grid grid-cols-2 gap-2 pt-1 border-t border-slate-800/50">
                  <div>
                    <label class="text-[10px] text-slate-400 block mb-0.5">Price (Rs.)</label>
                    <div class="flex gap-1">
                      <input id="price-${it.id}" type="number" value="${it.price}" class="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white font-mono focus:border-blue-500 outline-none">
                      <button onclick="updateItemPrice('${m.id}', '${it.id}', document.getElementById('price-${it.id}').value)" class="text-[10px] px-2 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded transition">Save</button>
                    </div>
                  </div>
                  <div>
                    <label class="text-[10px] text-slate-400 block mb-0.5">Stock Qty</label>
                    <div class="flex gap-1">
                      <input id="stock-${it.id}" type="number" value="${it.stock}" class="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white font-mono focus:border-blue-500 outline-none">
                      <button onclick="updateItemStock('${m.id}', '${it.id}', document.getElementById('stock-${it.id}').value)" class="text-[10px] px-2 py-1 bg-blue-600/80 hover:bg-blue-600 text-white rounded transition">Save</button>
                    </div>
                  </div>
                </div>
              </div>
            `;
          }).join('');

          return `
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-4">
              <div class="flex items-center justify-between pb-3 border-b border-slate-800">
                <div>
                  <h3 class="text-sm font-bold text-white">${m.name}</h3>
                  <span class="text-xs text-slate-500 font-mono">${m.id}</span>
                </div>
                <span class="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">${m.item_count} variants</span>
              </div>
              <div class="space-y-3 max-h-[600px] overflow-y-auto pr-1">
                ${itemsHtml}
              </div>
            </div>
          `;
        }).join('');
      } catch (err) {
        console.error('Error fetching merchants:', err);
      }
    }

    // Initial load
    fetchMerchants();
    fetchObjectives();

    // Auto-refresh objectives every 2 seconds for live demo feel
    setInterval(fetchObjectives, 2000);
  </script>
</body>
</html>
"""


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)


if __name__ == "__main__":
    main()
