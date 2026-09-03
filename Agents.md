DO NOT implement protocol functionality from scratch when an
official/reference implementation already provides it.

Reuse/adapt AP2, A2A and ACP implementations where appropriate.

Do not add frameworks or dependencies unless they solve a concrete
requirement.

The primary engineering focus is:
1. Shopping Agent
2. Merchant Agent
3. autonomous decision making
4. policy enforcement
5. WATCH/re-evaluation
6. Razorpay integration
7. failure handling

UI is secondary.

Never allow an LLM-generated decision to directly bypass deterministic
purchase constraints.

All money-moving operations must pass through the policy/authorization
layer.