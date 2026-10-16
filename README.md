# HomeCare – House Service Management Portal

A Flask + MongoDB web application where **customers** book household services, **administrators** manage services/providers
and assign jobs, and **providers** accept and complete the jobs assigned to them.

* Stack: Python 3.11+ (tested on 3.12), Flask, PyMongo, Flask-Login, Flask-WTF (CSRF), Werkzeug, Jinja2, Bootstrap 5 (bundled locally – no CDN needed).
* Design notes, schema, security checklist and concurrency limits: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

---
## 1. Prerequisites
| Software | Notes |
|---|---|
| Python 3.11 or newer | https://www.python.org/downloads/ – on Windows tick **"Add Python to PATH"** |
| MongoDB | Either **MongoDB Community Server** (local) or a free **MongoDB Atlas** cluster (cloud) |
| (Optional) MongoDB Compass | GUI to look at your data |

Check your install:
```
python --version
```
(On macOS/Linux use `python3`.)

## 2. Extract the project and create a virtual environment
Extract `HomeCare_Flask_MongoDB.zip` (right-click → *Extract All* on Windows), then open a terminal **inside the `HomeCare` folder**.

**Windows PowerShell**
```powershell
cd path\to\HomeCare
python -m venv venv
venv\Scripts\Activate.ps1
```
If PowerShell blocks the script: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then activate again.

**Windows Command Prompt**
```bat
cd path\to\HomeCare
python -m venv venv
venv\Scripts\activate.bat
```

**macOS / Linux**
```bash
cd path/to/HomeCare
python3 -m venv venv
source venv/bin/activate
```

## 3. Install dependencies
```
pip install -r requirements.txt
```

## 4. Set up MongoDB
**Option A – local MongoDB**: install MongoDB Community Server (it normally installs as a service listening on `127.0.0.1:27017`).
Nothing else is required; use `MONGO_URI=mongodb://127.0.0.1:27017/`.

**Option B – MongoDB Atlas**: create a free cluster → *Database Access*: create a user and password → *Network Access*: add your IP →
*Connect → Drivers* and copy the `mongodb+srv://…` string. Put your real user/password in it (URL-encode special characters).

## 5. Configure `.env`
**PowerShell**: `Copy-Item .env.example .env`  **Command Prompt**: `copy .env.example .env`  **macOS/Linux**: `cp .env.example .env`

Generate a secret key and paste it as `SECRET_KEY` in `.env`:
```
python -c "import secrets; print(secrets.token_hex(32))"
```
```
MONGO_URI=mongodb://127.0.0.1:27017/
SECRET_KEY=<paste the generated value>
```
The app refuses to start (with a clear message) if either value is missing or still the placeholder. **Never commit or share `.env`.**

## 6. Create the first administrator
```
python create_admin.py
```
You are prompted for name, email, phone and a password (hidden; min 10 characters with letters and digits).
There is no default admin and no public admin sign-up.

## 7. Seed sample services
```
python seed_data.py
```
Adds 12 services across the 10 categories (Plumbing … Pest Control). Safe to re-run – existing services are never overwritten.

## 8. Start the application
```
python app.py
```
## 9. Open the website
Browse to **http://127.0.0.1:5000**. Stop the server with `Ctrl + C`.
(Production: `gunicorn "app:create_app()"` on Linux behind HTTPS with `COOKIE_SECURE=true`. Debug mode is never enabled.)

## Deploy publicly on Render
The repository includes `render.yaml` to configure a Render web service.

1. Push this project to a GitHub repository. Do not commit `.env` or put database credentials in source code.
2. Create a MongoDB Atlas cluster and database user with read/write access to the app database. In Atlas **Network Access**, allow connections from Render. Render's outbound IPs may change; for a free service this may require allowing `0.0.0.0/0`. Use a strong, unique database password and never share the connection string.
3. In Render, choose **New → Blueprint**, connect the GitHub repository, and deploy the `render.yaml` blueprint.
4. In the Render service's environment settings, set `MONGO_URI` to the Atlas connection string. The blueprint generates `SECRET_KEY` and sets `COOKIE_SECURE=true`; keep those values private and do not replace the generated secret with a placeholder.
5. When deployment succeeds, open the `onrender.com` URL shown by Render. To add the initial administrator and sample services, run `create_admin.py` and `seed_data.py` in an environment configured with the same Atlas `MONGO_URI`.

The free web service can sleep when idle, and files written to its local filesystem (including uploaded images) are not durable across deploys/restarts. The checked-in static assets are unaffected. Use persistent/object storage before relying on user uploads in production.

## 10. Creating provider accounts
Providers cannot self-register. Log in as admin → **Users → Add provider** → fill in details, tick **Approve immediately**
(or approve later with the **Approve** button). Only *active and approved* providers can be assigned jobs.

## 11. Testing each role manually
1. **Customer** – *Register* → log in → *Services* (try search/category/price filters and pagination) → *View & Book* → pick a future date, time slot, address, description → *My Bookings* shows **Pending / Unpaid**. Use *Calendar* to view bookings and *Notifications* for updates.
2. **Admin** – log in with the admin account → *Bookings* → choose a provider in the row's drop-down → **Assign** (status becomes *Assigned*). Also try Services (add/edit/deactivate and upload an image), Users, Feedback, Reports, Calendar, and Notifications.
3. **Provider** – log in with the provider account → set weekly hours under *My availability* → *My Jobs* → **Accept** → **Start work** → **Mark completed**. (Reject sends the job back to the admin for reassignment.)
4. **Customer again** – the completed booking now has a **Review** button (rating 1–5 + comment, once per booking).

Use separate browsers/private windows to be logged in as different roles at the same time.

## 12. Running the automated tests
```
python -m pytest -v
```
Tests use an **in-memory `mongomock` database** created fresh for each test – your real MongoDB is never touched, and no MongoDB server is needed to run them.
They cover registration/duplicate email, login, password hashing, role authorization, service management and image uploads, booking validation/ownership/cancellation,
assignment and provider availability, notifications, calendar privacy, search pagination, invalid status transitions, provider isolation, review rules, invalid ObjectIds, CSRF, open-redirect, rate limiting and overlap/concurrency conflicts.

## 13. Troubleshooting
| Symptom | Fix |
|---|---|
| `CONFIGURATION ERROR: Missing required environment variable(s)` | Create `.env` from `.env.example` and fill in `MONGO_URI` and `SECRET_KEY`. |
| `DATABASE ERROR: could not connect to MongoDB` | Start the MongoDB service (Windows: *Services → MongoDB Server → Start*), or fix the Atlas URI/credentials/IP allow-list. |
| `ModuleNotFoundError` | Activate the virtual environment, then `pip install -r requirements.txt`. |
| PowerShell: *running scripts is disabled* | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Port 5000 in use | Set `PORT=5001` in `.env` (or the environment) and restart. |
| "Too many failed login attempts" | Wait ~15 minutes or restart the server (in-memory limiter). |
| Form shows "session expired" (400) | Reload the page (CSRF token expires after 1 hour). |
| Login keeps asking again over HTTPS/HTTP | `COOKIE_SECURE=true` only works over HTTPS; remove it for local http. |
| Atlas `+srv` DNS errors | `pip install "pymongo[srv]"` (included with recent PyMongo) and check your network/DNS. |

## 14. Not implemented / known limitations
* **Online payments** – none. `payment_status` is always `Unpaid`; nothing is ever marked paid.
* Notifications are in-app only; there are no email/SMS notifications, password reset, or email verification.
* Providers can set weekly working days/hours. Providers who have not saved a schedule retain unrestricted hours; booking start slots remain fixed at 08:00–17:00.
* Login rate limiting is in-memory per process (see `docs/ARCHITECTURE.md` for the production plan).
* Slot claim + booking update are not one transaction (no replica-set assumption) – see limitations in `docs/ARCHITECTURE.md`.
* Admin image uploads accept JPG, PNG, GIF, or WebP up to 1 MB. Other images can still be configured using relative paths inside `static/`.
* Times use the server's local time zone. Public service search is paginated; admin reports and management lists still use fixed result limits.
* Tests run against `mongomock`, not a real MongoDB server.
