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


class StockItem(BaseModel):
    sku: str
    stock: int


class StockBatchRequest(BaseModel):
    merchant: str
    items: list[StockItem]


class StockSingleRequest(BaseModel):
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
def update_stock_single(req: StockSingleRequest):
    m = MERCHANTS.get(req.merchant.lower())
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found")
    item = m.set_stock(req.sku, req.stock)
    if not item:
        raise HTTPException(status_code=404, detail="SKU not found")
    return {"success": True, "merchant": m.merchant_name, "sku": req.sku, "stock": req.stock}


@app.post("/api/stock/batch")
def update_stock_batch(req: StockBatchRequest):
    m = MERCHANTS.get(req.merchant.lower())
    if not m:
        raise HTTPException(status_code=404, detail="Merchant not found")
    updated = []
    for it in req.items:
        res = m.set_stock(it.sku, it.stock)
        if res:
            updated.append({"sku": it.sku, "stock": it.stock})
    return {"success": True, "merchant": m.merchant_name, "updated_count": len(updated)}


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
    body { background: #ffffff; color: #111827; padding: 32px; max-width: 960px; margin: 0 auto; }
    header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #e5e7eb; }
    h1 { font-size: 22px; font-weight: 700; color: #111827; }
    .header-links a { color: #4b5563; text-decoration: none; font-size: 13px; margin-left: 16px; }
    .header-links a:hover { color: #111827; text-decoration: underline; }

    /* Controls Bar on Top */
    .controls-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
    .tabs { display: flex; gap: 8px; }
    .tab-btn { padding: 8px 16px; background: #f3f4f6; border: 1px solid #e5e7eb; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; color: #4b5563; transition: all 0.15s; }
    .tab-btn:hover { background: #e5e7eb; }
    .tab-btn.active { background: #111827; color: #ffffff; border-color: #111827; }

    .btn-update { padding: 8px 22px; background: #111827; color: #ffffff; border: none; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; transition: background 0.15s; }
    .btn-update:hover { background: #374151; }
    .update-feedback { font-size: 12px; color: #059669; font-weight: 600; margin-right: 12px; display: none; }

    /* Table */
    table { width: 100%; border-collapse: collapse; margin-bottom: 32px; font-size: 14px; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }
    thead { background: #f9fafb; }
    th { text-align: left; padding: 12px 16px; font-size: 12px; font-weight: 600; color: #6b7280; text-transform: uppercase; letter-spacing: 0.04em; border-bottom: 1px solid #e5e7eb; }
    td { padding: 14px 16px; border-bottom: 1px solid #f3f4f6; vertical-align: middle; }
    tr:last-child td { border-bottom: none; }

    /* Counter Control */
    .counter-wrapper { display: inline-flex; align-items: center; border: 1px solid #d1d5db; border-radius: 6px; overflow: hidden; background: #ffffff; }
    .btn-counter { width: 28px; height: 28px; background: #f9fafb; border: none; font-size: 15px; font-weight: 600; color: #374151; cursor: pointer; user-select: none; display: flex; align-items: center; justify-content: center; transition: background 0.1s; }
    .btn-counter:hover { background: #e5e7eb; }
    .counter-input { width: 44px; height: 28px; border: none; text-align: center; font-size: 13px; font-weight: 600; color: #111827; outline: none; -moz-appearance: textfield; }
    .counter-input::-webkit-outer-spin-button, .counter-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
    .tag-oos { margin-left: 8px; font-size: 11px; font-weight: 600; color: #dc2626; background: #fef2f2; padding: 2px 6px; border-radius: 4px; display: none; }
    .tag-oos.visible { display: inline-block; }

    /* Objectives Box */
    .objectives-card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 20px; background: #ffffff; }
    .objectives-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
    .objectives-header h2 { font-size: 14px; font-weight: 600; color: #374151; }
    .obj-row { display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; margin-bottom: 8px; font-size: 13px; }
    .badge { padding: 3px 10px; border-radius: 9999px; font-size: 11px; font-weight: 700; }
    .badge-watch { background: #fffbeb; color: #b45309; border: 1px solid #fde68a; }
    .badge-done { background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }
    .empty-msg { font-size: 13px; color: #9ca3af; padding: 8px 0; }
  </style>
</head>
<body>

  <header>
    <h1>Merchant Stock Control</h1>
    <div class="header-links">
      <a href="/docs" target="_blank">Swagger API</a>
      <a href="http://127.0.0.1:8000" target="_blank">ADK Web UI (8000)</a>
    </div>
  </header>

  <!-- Controls Bar on Top -->
  <div class="controls-top">
    <div class="tabs" id="merchant-tabs"></div>
    <div style="display: flex; align-items: center;">
      <span id="update-msg" class="update-feedback">Updated!</span>
      <button class="btn-update" onclick="updateAllCurrentStock()">Update</button>
    </div>
  </div>

  <!-- Table: Name, Variant, Price (Rs), Stock -->
  <table>
    <thead>
      <tr>
        <th style="width: 40%;">Name</th>
        <th style="width: 20%;">Variant</th>
        <th style="width: 15%;">Price (Rs)</th>
        <th style="width: 25%;">Stock</th>
      </tr>
    </thead>
    <tbody id="items-tbody"></tbody>
  </table>

  <!-- Live Objectives -->
  <div class="objectives-card">
    <div class="objectives-header">
      <h2>Live Objectives (Watch Engine)</h2>
      <button onclick="loadObjectives()" style="font-size: 12px; background: none; border: none; color: #4b5563; cursor: pointer; text-decoration: underline;">Refresh</button>
    </div>
    <div id="objectives-list">
      <div class="empty-msg">No active shopping objectives.</div>
    </div>
  </div>

  <script>
    let merchantsData = [];
    let activeMerchantId = 'merchant_b'; // default to ShoeKart

    async function loadMerchants() {
      const res = await fetch('/api/merchants');
      merchantsData = await res.json();
      renderTabs();
      renderTable();
    }

    function renderTabs() {
      const container = document.getElementById('merchant-tabs');
      container.innerHTML = merchantsData.map(m => `
        <button class="tab-btn ${m.id === activeMerchantId ? 'active' : ''}" onclick="selectMerchant('${m.id}')">
          ${m.name}
        </button>
      `).join('');
    }

    function selectMerchant(id) {
      activeMerchantId = id;
      renderTabs();
      renderTable();
    }

    function renderTable() {
      const m = merchantsData.find(x => x.id === activeMerchantId);
      const tbody = document.getElementById('items-tbody');
      if (!m || !m.items || m.items.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="empty-msg">No items found.</td></tr>';
        return;
      }
      tbody.innerHTML = m.items.map(it => {
        const isOos = it.stock <= 0;
        return `
          <tr>
            <td>
              <div style="font-weight: 600; color: #111827;">${it.name}</div>
              <div style="font-size: 11px; color: #9ca3af; font-family: monospace;">${it.id}</div>
            </td>
            <td style="color: #4b5563;">Size ${it.attributes?.size || '-'} / ${it.attributes?.color || '-'}</td>
            <td style="font-weight: 600; color: #111827;">Rs. ${it.price.toLocaleString()}</td>
            <td>
              <div style="display: flex; align-items: center;">
                <div class="counter-wrapper">
                  <button type="button" class="btn-counter" onclick="changeCounter('${it.id}', -1)">-</button>
                  <input type="number" id="stock-${it.id}" class="counter-input" value="${it.stock}" min="0" oninput="handleStockInput('${it.id}')">
                  <button type="button" class="btn-counter" onclick="changeCounter('${it.id}', 1)">+</button>
                </div>
                <span id="oos-${it.id}" class="tag-oos ${isOos ? 'visible' : ''}">Out of stock</span>
              </div>
            </td>
          </tr>
        `;
      }).join('');
    }

    function changeCounter(sku, delta) {
      const input = document.getElementById('stock-' + sku);
      let val = parseInt(input.value) || 0;
      val = Math.max(0, val + delta);
      input.value = val;
      handleStockInput(sku);
    }

    function handleStockInput(sku) {
      const input = document.getElementById('stock-' + sku);
      const oosTag = document.getElementById('oos-' + sku);
      const val = parseInt(input.value) || 0;
      if (val <= 0) {
        oosTag.classList.add('visible');
      } else {
        oosTag.classList.remove('visible');
      }
    }

    async function updateAllCurrentStock() {
      const m = merchantsData.find(x => x.id === activeMerchantId);
      if (!m || !m.items) return;

      const itemsToUpdate = [];
      for (const it of m.items) {
        const input = document.getElementById('stock-' + it.id);
        if (input) {
          const val = parseInt(input.value) || 0;
          itemsToUpdate.push({ sku: it.id, stock: val });
        }
      }

      try {
        const res = await fetch('/api/stock/batch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ merchant: activeMerchantId, items: itemsToUpdate })
        });
        const data = await res.json();
        if (data.success) {
          const msg = document.getElementById('update-msg');
          msg.style.display = 'inline';
          setTimeout(() => { msg.style.display = 'none'; }, 2500);
          await loadMerchants();
          await loadObjectives();
        } else {
          alert('Update failed');
        }
      } catch (err) {
        alert('Error: ' + err);
      }
    }

    async function loadObjectives() {
      try {
        const res = await fetch('/api/objectives');
        const list = await res.json();
        const container = document.getElementById('objectives-list');
        if (!list || list.length === 0) {
          container.innerHTML = '<div class="empty-msg">No active shopping objectives.</div>';
          return;
        }
        container.innerHTML = list.map(o => {
          let badgeClass = 'badge-watch';
          if (o.status === 'COMPLETED') badgeClass = 'badge-done';

          let details = '';
          if (o.purchase && o.purchase.success) {
            details = `<div style="color: #059669; font-size: 12px; margin-top: 2px;">Purchased from ${o.purchase.merchant} for Rs. ${o.purchase.amount_paid_inr.toLocaleString()}</div>`;
          } else if (o.reason) {
            details = `<div style="color: #b45309; font-size: 12px; margin-top: 2px;">${o.reason}</div>`;
          }

          return `
            <div class="obj-row">
              <div>
                <div style="font-weight: 600; color: #111827;">"${o.intent}"</div>
                ${details}
              </div>
              <span class="badge ${badgeClass}">${o.status}</span>
            </div>
          `;
        }).join('');
      } catch (e) {
        console.error(e);
      }
    }

    // Initial load
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
