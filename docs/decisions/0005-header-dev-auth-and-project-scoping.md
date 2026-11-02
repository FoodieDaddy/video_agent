# ADR 0005 — Header auth for development, project-scoped authorization

* **Status:** Accepted
* **Date:** 2026-11-02
* **Deciders:** platform team

## Context

The product needs three different things from authentication at once:

* **Local development and demo** must work with no identity provider: `uvicorn` starts, the
  console is usable, and the pipeline can be driven end to end without a login flow.
* **Tests** must be able to act as different users in one process, cheaply, to prove isolation.
* **Production** must not have a bypass at all; the real identity is decided by the gateway.

Rolling a full user/password/JWT stack now would be security theatre inside a demo product,
and it would slow the API layer while the domain is still being shaped.

## Decision

* **Development identity comes from headers.** `X-User-Id` and `X-User-Role`, resolved by
  `core/security.py::resolve_user`, gated by `auth.allow_dev_auth` (true in `development` and
  `test`, false in `production`).
* **A demo administrator exists.** When `X-User-Id` is absent the caller becomes
  `auth.demo_user_id` (`user_demo`) with `role="admin"`, so the console is instantly usable.
  The role header is deliberately ignored for that id: sending `X-User-Id: user_demo` downgrades
  it to a plain member (this asymmetry is what makes the 403 test meaningful).
* **Authorization is project-scoped.** `api/deps.py` exposes `project_scope` (owner or any
  member, read) and `owner_project` (owner, or a member whose role is `editor` — mutations:
  uploads, review decisions, workflow control) plus `AdminDep` for `/admin/*`. Cross-project
  access returns `403 permission_denied` and other users' projects are simply absent from
  listings (`services/projects.get_project` owns that check).
* **Every new row records `created_by` / `owner_id`**, so authorization never depends on the
  request context after the fact.
* **Production is gateway-authenticated.** `auth.allow_dev_auth: false` makes header auth inert;
  the gateway injects a trusted identity and the app never sees credentials.

## Consequences

**Positive**

* Zero setup for the demo and tests; the console and `TestClient` share one code path.
* Isolation is genuinely tested (`test_api.py` asserts a 403 and an empty listing for a second
  user), not just assumed.
* Adding real auth later is a single function (`resolve_user`) plus a token validator — the
  rest of the code already works with `user.id` / `user.role`.
* No password storage, no session store, no secret rotation to operate today.

**Negative**

* The header path is a real bypass if `allow_dev_auth` is ever true in production; the config
  must be treated as a security boundary and is called out in the production environment file
  and README.
* Role granularity is coarse (admin vs user); fine-grained permissions (per-stage reviewer
  rights) need a policy layer.
* The demo identity's admin default surprises callers who send its id explicitly, as the
  console did (symptom: `/admin/status` returning 403). Documented in the API reference.
* Multi-tenant isolation is per project only — no organization hierarchy.

## Alternatives considered

1. **Full JWT/OAuth implementation now** — realistic production shape, but significant work with
   no product value while the domain is in flux; also makes offline demo harder.
2. **No auth at all** — simplest; loses the isolation guarantees the API already tests, and
   would need a breaking change later.
3. **Session cookie auth** — convenient for the browser console, awkward for CLI/tests and for
   the SSE stream.
4. **OIDC proxy as the only option** — correct for production, unusable for a laptop demo
   without a provider.

## Revisit when

* The first real deployment happens (introduce a token validator + organization model, keep the
  header path behind `allow_dev_auth` for tests).
* Per-stage review permissions are required (introduce roles: producer, reviewer, editor).
* Multiple tenants appear — then every query needs a tenant predicate, not just a project one.
