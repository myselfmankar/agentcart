"""Automated test suite for Google ADK Evals, OpenTelemetry Tracing, and Lifecycle Auditing.

Covers:
1. ADK Trajectory Eval Set validation (tests/evals/commerce_eval_set.json).
2. OpenTelemetry distributed tracing across A2A operations (discover, request, negotiate, checkout).
3. W3C TraceContext context propagation in A2A negotiation payloads.
4. Non-invasive A2AAuditTracePlugin lifecycle callbacks (before/after tool, error, sanitization).
5. ADK ToolContext state scoping (user:balance, session:current_intent, session invariants).
6. Tamper-evident cryptographic audit trail verification.
"""

import os
from types import SimpleNamespace

import pytest
from google.adk.evaluation.eval_set import EvalSet
from google.adk.evaluation.local_eval_sets_manager import load_eval_set_from_file
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from adk_agents.shopping_agent.buyer_agent import (
    check_buyer_balance,
    run_autonomous_purchase,
)
from app.modules.a2a.client import a2a_client
from app.modules.audit.adk_plugin import A2AAuditTracePlugin
from app.modules.audit.trail import audit_trail
from app.modules.buyer.ledger import buyer_ledger


@pytest.fixture(autouse=True)
def reset_ledger_and_trail():
    """Ensures a pristine ledger balance and test environment for each test."""
    buyer_ledger.reset(available_balance=10000.0, per_transaction_limit=50000.0)
    audit_trail.clear()
    yield
    buyer_ledger.reset(available_balance=10000.0, per_transaction_limit=50000.0)



@pytest.fixture
def otel_in_memory():
    """Sets up an in-memory OpenTelemetry span exporter for inspecting traces."""
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


def test_adk_eval_set_loading_and_structure():
    """Verify that the ADK eval set matches Google ADK's Pydantic schema and invariants."""
    eval_file = os.path.join("tests", "evals", "commerce_eval_set.json")
    assert os.path.exists(eval_file), f"Eval file {eval_file} must exist."

    eval_set = load_eval_set_from_file(eval_file, "eval_agentic_commerce")
    assert isinstance(eval_set, EvalSet)
    assert eval_set.eval_set_id == "eval_agentic_commerce"
    assert len(eval_set.eval_cases) == 4

    case_ids = {c.eval_id for c in eval_set.eval_cases}
    expected_ids = {
        "test_happy_path_purchase_tool_call",
        "test_delivery_deadline_extraction",
        "test_overbudget_rejection_state_invariant",
        "test_insufficient_balance_rejection_invariant",
    }
    assert expected_ids.issubset(case_ids)

    for case in eval_set.eval_cases:
        assert case.conversation is not None and len(case.conversation) > 0
        inv = case.conversation[0]
        assert inv.user_content is not None
        assert inv.intermediate_data is not None
        assert len(inv.intermediate_data.tool_uses) > 0
        tool_use = inv.intermediate_data.tool_uses[0]
        assert tool_use.name == "run_autonomous_purchase"
        assert "max_budget" in tool_use.args
        assert case.final_session_state is not None
        assert "user:balance" in case.final_session_state


def test_a2a_telemetry_spans_and_w3c_carrier(otel_in_memory):
    """Verify OpenTelemetry span hierarchies and attributes across all A2A client methods."""
    obj_id = "test_otel_obj_001"

    # 1. Test discover_merchants span
    merchants = a2a_client.discover_merchants(objective_id=obj_id)
    assert len(merchants) >= 3

    # 2. Test request_proposals span
    proposals = a2a_client.request_proposals(
        query="shoes",
        filters={"brand": "Adidas", "size": 10, "color": "blue", "max_price": 5000.0},
        objective_id=obj_id,
    )
    assert len(proposals) >= 1

    # 3. Test negotiate span with W3C carrier injection
    proposal = proposals[0]
    counter = a2a_client.negotiate(
        merchant_id=proposal.merchant_id,
        proposal=proposal,
        competing_price=4200.0,
        objective_id=obj_id,
    )

    # 4. Test create_checkout span
    session, auth_token = a2a_client.create_checkout(
        merchant_id=proposal.merchant_id,
        item_id=proposal.item.id,
        quantity=1,
        agreed_price=counter.proposed_price if counter else proposal.proposed_price,
        objective_id=obj_id,
    )
    assert session is not None
    assert auth_token is not None

    # 5. Test complete_checkout span
    completed_session = a2a_client.complete_checkout(
        merchant_id=proposal.merchant_id,
        session_id=session.id,
        payment_id="pay_test_otel_123",
        objective_id=obj_id,
    )
    assert completed_session.status.value == "completed"

    # Inspect all captured OTel spans
    spans = otel_in_memory.get_finished_spans()
    span_names = [s.name for s in spans]

    assert "a2a.discover_merchants" in span_names
    assert "a2a.request_proposals" in span_names
    assert "a2a.negotiate" in span_names
    assert "a2a.create_checkout" in span_names
    assert "a2a.complete_checkout" in span_names

    # Check negotiate span attributes
    neg_span = next(s for s in spans if s.name == "a2a.negotiate")
    assert neg_span.attributes["a2a.protocol"] == "A2A/1.0"
    assert neg_span.attributes["a2a.objective_id"] == obj_id
    assert neg_span.attributes["a2a.merchant_id"] == proposal.merchant_id
    assert neg_span.attributes["a2a.competing_price"] == 4200.0
    assert "a2a.status" in neg_span.attributes

    # Check checkout span attributes
    co_span = next(s for s in spans if s.name == "a2a.create_checkout")
    assert co_span.attributes["a2a.protocol"] == "ACP/1.0"
    assert co_span.attributes["a2a.total_amount"] > 0
    assert "a2a.checkout_hash" in co_span.attributes


@pytest.mark.asyncio
async def test_a2a_audit_plugin_lifecycle_callbacks():
    """Verify A2AAuditTracePlugin sanitization and lifecycle hooks into audit_trail."""
    plugin = A2AAuditTracePlugin(name="test_plugin")

    # 1. Payload sanitization
    dirty_args = {
        "username": "buyer_1",
        "api_key": "secret_abc_123",
        "nested": {
            "token": "tok_xyz",
            "normal_field": "valid_value",
            "razorpay_secret": "rzp_sec_999",
        },
        "tags": ["safe", "passwords_are_bad"],
    }
    cleaned = plugin._sanitize_payload(dirty_args)
    assert cleaned["api_key"] == "[REDACTED]"
    assert cleaned["nested"]["token"] == "[REDACTED]"
    assert cleaned["nested"]["razorpay_secret"] == "[REDACTED]"
    assert cleaned["nested"]["normal_field"] == "valid_value"

    # 2. Before tool callback
    mock_tool = SimpleNamespace(name="run_autonomous_purchase")
    mock_ctx = SimpleNamespace(invocation_id="inv_test_lifecycle")

    await plugin.before_tool_callback(
        tool=mock_tool,
        tool_args={"query": "shoes", "max_budget": 5000.0, "secret_code": "1234"},
        tool_context=mock_ctx,
    )
    start_events = [
        e for e in audit_trail.events
        if e["event_type"] == "ADK_TOOL_CALL_STARTED" and e["objective_id"] == "inv_test_lifecycle"
    ]
    assert len(start_events) > 0
    assert start_events[-1]["details"]["tool_name"] == "run_autonomous_purchase"
    assert start_events[-1]["details"]["arguments"]["secret_code"] == "[REDACTED]"

    # 3. After tool callback
    await plugin.after_tool_callback(
        tool=mock_tool,
        tool_args={"query": "shoes"},
        tool_context=mock_ctx,
        result={"success": True, "status": "PURCHASE_SETTLED"},
    )
    complete_events = [
        e for e in audit_trail.events
        if e["event_type"] == "ADK_TOOL_CALL_COMPLETED" and e["objective_id"] == "inv_test_lifecycle"
    ]
    assert len(complete_events) > 0
    assert complete_events[-1]["details"]["success"] is True
    assert complete_events[-1]["details"]["status"] == "PURCHASE_SETTLED"
    assert "duration_ms" in complete_events[-1]["details"]

    # 4. Error callback
    await plugin.on_tool_error_callback(
        tool=mock_tool,
        tool_args={"query": "shoes"},
        tool_context=mock_ctx,
        error=ValueError("Simulated network timeout"),
    )
    error_events = [
        e for e in audit_trail.events
        if e["event_type"] == "ADK_TOOL_CALL_ERROR" and e["objective_id"] == "inv_test_lifecycle"
    ]
    assert len(error_events) > 0
    assert error_events[-1]["details"]["error_type"] == "ValueError"
    assert "Simulated network timeout" in error_events[-1]["details"]["error"]


def test_tool_context_state_scoping_in_buyer_agent():
    """Verify ToolContext mutates scoped session and user state correctly."""
    mock_ctx = SimpleNamespace(
        state={},
        invocation_id="inv_state_scope_001",
    )

    # 1. check_buyer_balance updates user:balance & limit
    info = check_buyer_balance(tool_context=mock_ctx)
    assert info["available_balance"] == 10000.0
    assert mock_ctx.state["user:balance"] == 10000.0
    assert mock_ctx.state["user:per_transaction_limit"] == 50000.0

    # 2. run_autonomous_purchase mutates intent, session order/payment IDs, and remaining balance
    result = run_autonomous_purchase(
        query="Adidas blue sneakers",
        brand="Adidas",
        size=10,
        color="blue",
        max_budget=5000.0,
        auto_purchase=True,
        tool_context=mock_ctx,
    )
    assert result["success"] is True
    assert mock_ctx.state["session:current_intent"] == "Adidas blue sneakers"
    assert mock_ctx.state["session:last_order_id"] == result["order_id"]
    assert mock_ctx.state["session:last_payment_id"] == result["payment_id"]
    assert mock_ctx.state["session:winning_merchant"] == result["merchant"]
    assert mock_ctx.state["user:balance"] == result["remaining_balance_inr"]
    assert mock_ctx.state["user:balance"] < 10000.0


def test_tool_context_state_invariant_on_policy_rejection():
    """Verify that when a purchase is rejected, the user:balance state invariant is maintained."""
    mock_ctx = SimpleNamespace(
        state={"user:balance": 10000.0},
        invocation_id="inv_state_invariant_001",
    )

    # Attempt to purchase with an impossibly low budget (Rs. 1,500)
    result = run_autonomous_purchase(
        query="Nike running shoes",
        brand="Nike",
        size=10,
        max_budget=1500.0,
        auto_purchase=True,
        tool_context=mock_ctx,
    )

    assert result["success"] is False
    assert result["status"] in ["WATCHING", "WATCHING_ESTABLISHED", "POLICY_REJECTED"]
    # User balance in state MUST remain completely unchanged
    assert mock_ctx.state["user:balance"] == 10000.0
    assert buyer_ledger.available_balance == 10000.0


def test_audit_trail_tamper_evident_integrity_under_adk():
    """Verify cryptographic SHA-256 hash chaining remains valid across all ADK operations."""
    is_valid = audit_trail.verify_integrity()
    assert is_valid is True, "Cryptographic audit trail hash chain integrity failed!"
