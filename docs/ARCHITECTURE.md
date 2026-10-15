# HomeCare – Architecture & Security Notes

## Layout
| Folder | Purpose |
|---|---|
| `app.py` | Application factory `create_app()`, error handlers, security headers. Entry point for the web server. |
| `config.py` | Reads `.env`; raises a clear `ConfigError` if `MONGO_URI` / `SECRET_KEY` are missing or insecure. |
| `models/` | MongoDB access per collection (`user`, `service`, `booking`, `review`) + `db.py` (connection, indexes, validators). |
| `services/` | Business rules: `booking_service.py` (workflow, conflict prevention), `report_service.py`. |
| `routes/` | Flask blueprints: `main`, `auth`, `customer`, `provider`, `admin`. Every protected route uses `role_required`. |
| `utils/` | Validators, decorators, open-redirect check, login rate limiter. |
| `create_admin.py`, `seed_data.py` | CLI entry points (initial admin, sample services). |

## Collections
`users`, `services`, `bookings`, `reviews` as specified, plus one internal collection:

* `provider_slots` – `{provider_id, block (datetime), booking_id}`; one document per 30‑minute block a provider is committed to.

Extra fields (additions to the requested schema): `bookings.start_dt` / `duration_minutes` (for schedule queries),
`bookings.cancelled_by`, `reviews.service_id` (to show reviews on a service page).

Indexes: unique `users.email`; unique `services.name`; `bookings(customer_id,start_dt)` (customer history);
`bookings(provider_id,start_dt)` (provider schedule); unique `reviews.booking_id`; unique `provider_slots(provider_id,block)`.
`$jsonSchema` validators (moderate level) are applied on startup where the MongoDB tier allows it.

## Booking status machine (enforced server-side)
```
Pending -> Assigned -> Accepted -> In Progress -> Completed
             |  ^         
             v  |(admin reassign to a DIFFERENT provider)
          Rejected
Pending / Assigned / Accepted / Rejected -> Cancelled
```
The browser only sends an *action* (`accept`, `reject`, `start`, `complete`, `cancel`, `assign`). The server maps the action
to the one allowed transition and applies it with `find_one_and_update` whose filter contains the **required current status
and the provider/customer id** (compare-and-set). A stale or forged request simply matches nothing and gets HTTP 404/409.

Cancellation: customers may cancel Pending/Assigned/Rejected bookings any time and Accepted bookings until 2 hours before the
start. Admins may cancel any non-final booking. In Progress, Completed and Cancelled are never cancellable.

## Double-booking prevention and its limits
1. On assignment the server inserts one `provider_slots` document per 30-minute block of the job.
2. A **unique index** on `(provider_id, block)` makes MongoDB itself reject overlapping claims, even from simultaneous
   requests/processes. On a duplicate-key error the partial claims are rolled back and the admin sees HTTP 409.
3. The booking is then moved to *Assigned* with a status/provider compare-and-set. If that loses a race, the new claims are removed.
4. Claims are released when a job is Rejected, Cancelled, Completed or reassigned.

Limitations (honest list):
* Without a replica set, MongoDB cannot wrap "claim slots" and "update booking" in one transaction. If the process crashes between
  the two writes, orphaned claims can remain (the provider would look busy for that time). A periodic cleanup job comparing
  `provider_slots` with `bookings` would fix this; it is not included. (Atlas always provides a replica set, so you could upgrade
  `assign_provider` to use `session.with_transaction`.)
* Accepting a job needs no new check because the time was already claimed at assignment.
* Customers are not blocked from booking the same slot as other customers – conflicts are about *providers*, resolved at assignment.
* Times are the server's local time; there is no per-user time zone support.
* Tests use `mongomock`; the concurrency test exercises threads in one process. Please also test against a real MongoDB.

## Security checklist → implementation
| Requirement | Where |
|---|---|
| Password hashing | Werkzeug `generate_password_hash` (`models/user.py`) |
| Role checks on every protected route | `utils/decorators.role_required` |
| CSRF on all POSTs | `Flask-WTF CSRFProtect` + hidden `csrf_token` in every form (logout is a POST form too) |
| IDOR protection | Customer queries include `customer_id`; provider actions include `provider_id`; wrong owner → 404 |
| ObjectId validation | `utils.validators.to_object_id / oid_or_404` – invalid ids return 404, never a 500 |
| No public admin/provider signup | `/register` hard-codes `role="customer"`; admins via `create_admin.py`, providers via admin UI |
| Open redirect | `utils.security.is_safe_redirect` (only same-site relative paths) |
| Session cookies | HttpOnly, SameSite=Lax, optional Secure (`COOKIE_SECURE=true`), 8h lifetime, `session.clear()` on login |
| Rate limiting | In-memory sliding window: 5 failures / 15 min per IP+email (and per IP). **Production plan:** move to Redis-backed Flask-Limiter because in-memory state resets on restart and is per-process. Behind a reverse proxy also configure `werkzeug.middleware.proxy_fix.ProxyFix` so `remote_addr` is the real client IP. |
| No stack traces | Global error handlers render friendly pages; details go to the server log only |
| Debug mode | `app.run(debug=False)` is hard-coded |
| Headers | CSP (`default-src 'self'`), X-Frame-Options, nosniff, Referrer-Policy; no-store on dynamic GET pages |
| Payments | No payment integration. `payment_status` stays `Unpaid`; nothing is ever marked paid. |
