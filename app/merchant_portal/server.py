"""Simple, Minimal Merchant Stock Control & Live Watch Portal."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.merchants import merchant_a, merchant_b, merchant_c
from app.modules.watch.objective import objective_store

MERCHANTS = {
    "merchant_a": merchant_a,
    "urbankicks": merchant_a,
    "merchant_b": merchant_b,
    "shoekart": merchant_b,
    "merchant_c": merchant_c,
    "fastfeet": merchant_c,
}

app = FastAPI(title="Merchant Stock Control", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StockRequest(BaseModel):
    merchant: str
    sku: str
    stock: int


@app.get("/api/merchants")
def get_merchants():
    results = []
    for m_id in ["merchant_a", "merchant_b", "merchant_c"]:
        m = MERCHANTS[m_id]
        m.reload_from_disk()
        results.append({
            "id": m.merchant_id,
            "name": m.merchant_name,
            "items": m.get_full_catalog(),
        })
    return results


@app.post("/api/stock")
def update_stock(req: StockRequest):
    m = MERCHANTS.get(req.merchant.lower())
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found")
    item = m.set_stock(req.sku, req.stock)
    if not item:
        raise HTTPException(status_code=404, detail="SKU not found")
    return {"success": True, "merchant": m.merchant_name, "sku": req.sku, "stock": req.stock}


@app.get("/api/objectives")
def get_objectives():
    objs = objective_store.get_all_objectives()
    return [
        {
            "id": o.objective_id,
            "status": o.status.value,
            "intent": o.user_intent.get("description") or o.user_intent.get("query"),
            "reason": o.watch_reason,
            "purchase": o.purchase_result,
        }
        for o in objs
    ]


@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Merchant Stock Control</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background: #f9fafb; color: #111827; padding: 24px; max-width: 1050px; margin: 0 auto; }
    header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #e5e7eb; }
    h1 { font-size: 20px; font-weight: 600; }
    .header-links a { color: #2563eb; text-decoration: none; font-size: 13px; margin-left: 16px; }
    .header-links a:hover { text-decoration: underline; }
    .card { background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 20px; margin-bottom: 24px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
    h2 { font-size: 15px; font-weight: 600; margin-bottom: 12px; color: #374151; }
    .tabs { display: flex; gap: 8px; margin-bottom: 16px; }
    .tab-btn { padding: 6px 14px; background: #f3f4f6; border: 1px solid #d1d5db; border-radius: 6px; font-size: 13px; font-weight: 500; cursor: pointer; }
    .tab-btn.active { background: #111827; color: #ffffff; border-color: #111827; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th { text-align: left; padding: 10px 12px; border-bottom: 1px solid #e5e7eb; color: #6b7280; font-weight: 500; }
    td { padding: 10px 12px; border-bottom: 1px solid #f3f4f6; }
    tr:last-child td { border-bottom: none; }
    .stock-input { width: 65px; padding: 4px 8px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 13px; text-align: center; }
    .btn-save { padding: 4px 10px; background: #2563eb; color: #fff; border: none; border-radius: 4px; font-size: 12px; cursor: pointer; margin-left: 6px; }
    .btn-save:hover { background: #1d4ed8; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 9999px; font-size: 11px; font-weight: 600; }
    .badge-in { background: #ecfdf5; color: #059669; }
    .badge-out { background: #fef2f2; color: #dc2626; }
    .badge-watch { background: #fffbeb; color: #d97706; border: 1px solid #fde68a; }
    .badge-done { background: #ecfdf5; color: #059669; border: 1px solid #a7f3d0; }
    .obj-item { padding: 12px; background: #fafafa; border: 1px solid #e5e7eb; border-radius: 6px; margin-bottom: 8px; font-size: 13px; display: flex; justify-content: space-between; align-items: center; }
    .obj-info { line-height: 1.4; }
    .obj-intent { font-weight: 500; color: #111827; }
    .obj-meta { font-size: 12px; color: #6b7280; }
    .empty-state { color: #9ca3af; font-size: 13px; padding: 12px 0; }
  </style>
</head>
<body>

  <header>
    <div>
      <h1>Merchant Stock Control</h1>
      <div style="font-size: 12px; color: #6b7280; margin-top: 2px;">Inspect real store inventory and adjust stock to trigger live watch re-evaluations.</div>
    </div>
    <div class="header-links">
      <a href="/docs" target="_blank">Swagger API (/docs)</a>
      <a href="http://127.0.0.1:8000" target="_blank">ADK Web UI (8000)</a>
    </div>
  </header>

  <!-- Stock Control -->
  <div class="card">
    <div class="tabs" id="merchant-tabs"></div>
    <table>
      <thead>
        <tr>
          <th>Product SKU</th>
          <th>Name</th>
          <th>Variant</th>
          <th>Price</th>
          <th>Status</th>
          <th>Stock Control</th>
        </tr>
      </thead>
      <tbody id="items-tbody"></tbody>
    </table>
  </div>

  <!-- Live Objectives -->
  <div class="card">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
      <h2>Live Shopping Objectives (Watch State)</h2>
      <button onclick="loadObjectives()" style="font-size: 12px; background: none; border: none; color: #2563eb; cursor: pointer;">Refresh</button>
    </div>
    <div id="objectives-list">
      <div class="empty-state">No active shopping objectives yet.</div>
    </div>
  </div>

  <script>
    let merchantsData = [];
    let activeMerchantId = 'merchant_b'; // default to ShoeKart

    async function loadMerchants() {
      const res = await fetch('/api/merchants');
      merchantsData = await res.json();
      renderTabs();
      renderItems();
    }

    function renderTabs() {
      const tabs = document.getElementById('merchant-tabs');
      tabs.innerHTML = merchantsData.map(m => `
        <button class="tab-btn ${m.id === activeMerchantId ? 'active' : ''}" onclick="selectMerchant('${m.id}')">
          ${m.name}
        </button>
      `).join('');
    }

    function selectMerchant(id) {
      activeMerchantId = id;
      renderTabs();
      renderItems();
    }

    function renderItems() {
      const m = merchantsData.find(x => x.id === activeMerchantId);
      const tbody = document.getElementById('items-tbody');
      if (!m || !m.items || m.items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No items found.</td></tr>';
        return;
      }
      tbody.innerHTML = m.items.map(it => {
        const isOos = it.stock <= 0;
        const statusBadge = isOos
          ? '<span class="badge badge-out">Out of Stock (0)</span>'
          : `<span class="badge badge-in">${it.stock} In Stock</span>`;

        return `
          <tr>
            <td style="font-family: monospace; font-size: 12px; color: #4b5563;">${it.id}</td>
            <td><strong>${it.name}</strong></td>
            <td style="color: #6b7280;">Size ${it.attributes?.size || '-'} / ${it.attributes?.color || '-'}</td>
            <td>Rs. ${it.price.toLocaleString()}</td>
            <td>${statusBadge}</td>
            <td>
              <input type="number" id="input-${it.id}" class="stock-input" value="${it.stock}" min="0">
              <button class="btn-save" onclick="saveStock('${m.id}', '${it.id}')">Save</button>
            </td>
          </tr>
        `;
      }).join('');
    }

    async function saveStock(merchantId, sku) {
      const input = document.getElementById('input-' + sku);
      const newStock = parseInt(input.value);
      try {
        const res = await fetch('/api/stock', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ merchant: merchantId, sku: sku, stock: newStock })
        });
        const data = await res.json();
        if (data.success) {
          await loadMerchants();
          await loadObjectives();
        } else {
          alert('Failed to update stock');
        }
      } catch (e) {
        alert('Error: ' + e);
      }
    }

    async function loadObjectives() {
      try {
        const res = await fetch('/api/objectives');
        const list = await res.json();
        const container = document.getElementById('objectives-list');
        if (list.length === 0) {
          container.innerHTML = '<div class="empty-state">No active shopping objectives yet.</div>';
          return;
        }
        container.innerHTML = list.map(o => {
          let badgeClass = 'badge-watch';
          if (o.status === 'COMPLETED') badgeClass = 'badge-done';

          let detail = o.reason ? `<div class="obj-meta">${o.reason}</div>` : '';
          if (o.purchase && o.purchase.success) {
            detail = `<div class="obj-meta" style="color: #059669; font-weight: 500;">Purchased ${o.purchase.item_purchased} from ${o.purchase.merchant} for Rs. ${o.purchase.amount_paid_inr.toLocaleString()}</div>`;
          }

          return `
            <div class="obj-item">
              <div class="obj-info">
                <div class="obj-intent">"${o.intent}"</div>
                ${detail}
              </div>
              <div>
                <span class="badge ${badgeClass}">${o.status}</span>
              </div>
            </div>
          `;
        }).join('');
      } catch (e) {
        console.error(e);
      }
    }

    loadMerchants();
    loadObjectives();
    setInterval(loadObjectives, 2000);
  </script>
</body>
</html>
"""


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)


if __name__ == "__main__":
    main()
