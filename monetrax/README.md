# Monetrax
*Your Money. Your Direction.*

A full-stack personal finance app for college students: track allowances and expenses, set budgets,
save toward goals, and understand spending habits.

**Stack:** Python · Flask · Flask-Login · Flask-SQLAlchemy · Werkzeug hashing · SQLite (local) / PostgreSQL (production)
· HTML · Tailwind CSS · Vanilla JS · Chart.js · Press Start 2P + VT323 · hand-drawn pixel icons

---

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py                        # http://127.0.0.1:5000
```

The SQLite database (`instance/monetrax.sqlite3`) is created on first run. Set `SECRET_KEY`
(see `.env.example`) so sessions survive restarts.

Run the tests: `pytest`

## Deploy to Render

1. Push this folder to a GitHub repository.
2. In Render choose **New → Blueprint** and select the repo. `render.yaml` creates a web service and a
   free PostgreSQL database, generates `SECRET_KEY`, and connects `DATABASE_URL`.
3. On start, `flask --app app init-db` creates the tables, then Gunicorn serves the app.

`postgres://` URLs from Render are converted automatically for SQLAlchemy + psycopg 3.

## Settings

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | random each start | Signs session cookies. **Required in production.** |
| `DATABASE_URL` | SQLite in `instance/` | PostgreSQL connection string in production. |
| `APP_TIMEZONE` | `Asia/Manila` | Defines "today", weeks (Mon–Sun) and months. |
| `MONETRAX_REQUIRE_SCHOOL_EMAIL` | `true` | Only `.edu` / `.edu.xx` emails can register. |
| `SECURE_COOKIES` | `false` | Set `true` behind HTTPS. |

## Modules

| Module | What it does |
|---|---|
| **Auth** | Register, sign in (remember me), sign out; hashed passwords; duplicate-email check; CSRF on every form. |
| **Dashboard** | "Good day, *Name*!", Total Allowance / Expenses / Remaining Balance / Savings, income-vs-expense chart, daily spending trend, category breakdown, recent transactions, budget and savings overviews, Monetrax Insights. |
| **Transactions** | Add, edit, delete; search; filter by type, category and date range; sort by date or amount; pagination; CSV export. |
| **Wallets** | Cash, GCash, Maya, bank and other wallets with live balances. Every transaction says which wallet it used. **Move money** records cash-ins and withdrawals without counting them as income or spending. Wallets with history are hidden instead of deleted. |
| **Recurring** | Allowance, rent, load and subscriptions added automatically on schedule (daily, weekly, every 2 weeks, monthly). Missed dates are filled in on your next visit. Pause, skip the next date, edit or stop. Set up from Transactions → Recurring, or with **Repeat** on any new transaction. |
| **Safe to spend today** | Dashboard figure: money in spendable wallets, minus bills due before your next allowance, divided by the days until it arrives. Without a recurring allowance it plans to the end of the month. |
| **Budget Management** | Weekly or monthly limits per expense category; spent, remaining and % used with progress bars. |
| **Savings Goals** | Target amount and optional date; add or withdraw money; history; weekly pace to hit the date. |
| **Analytics & Reports** | Any period (this month, last month, 3/6 months, year, custom); comparison with the previous period; charts; category table; largest expenses; CSV export; print-friendly. |
| **Notifications** | Budget alerts at **75%**, **90%** and **over 100%**; savings milestones (50%, reached, due within 7 days, overdue); read/unread, dismiss. |
| **Settings** | Profile (school, program, year level), appearance (light, dark or match device), currency, alert toggles, custom categories, password change, account deletion. |
| **Pixel UI** | A full retro-game look: chunky pixel frames with hard drop shadows, notched corners, a grid backdrop with CRT scanlines, segmented HP-style progress bars, a spinning coin on Safe to spend, an RPG ▶ cursor in the menu, stepped charts and a pixelated doughnut. Headings use Press Start 2P and body text uses VT323. All 96 icons are hand-drawn 16×16 two-tone pixel art in `static/js/pixel-icons.js` (it replaces Lucide and keeps the same `<i data-lucide="…">` markup). The look lives in `static/css/pixel.css`, which loads last, so deleting that one line in `base.html` brings back the smooth design. |
| **Motion** | Staggered page entrances, numbers that count up, charts that grow in as you scroll to them, an animated sign-in illustration with a self-drawing logo and pointer parallax, a circular reveal when switching themes, a loading bar and busy buttons while pages load, and success messages that dismiss themselves. All of it lives in `static/css/motion.css` and `static/js/motion.js`, and all of it turns off when the device asks for reduced motion. |
| **Light & dark mode** | Sun/moon toggle in the top bar and on the sign-in pages. The choice is saved to the account (follows you to other devices) and in the browser, and applied before the page paints. Colors live as tokens in `static/css/theme.css`. |

### Financial rules
- **Total Income** = sum of income transactions · **Total Expenses** = sum of expense transactions
- **Remaining Balance** = Total Income − Total Expenses
- **Wallet balance** = starting balance + income − expenses + transfers in − transfers out. The total across
  wallets can be higher than Remaining Balance by the starting balances you entered.
- **Safe to spend today** = (spendable wallets now + spent today − bills due before next allowance) ÷ days until it.
- **Total Savings** = money added to savings goals minus withdrawals. Savings are tracked separately and
  do not change the Remaining Balance.
- Every figure is calculated from the signed-in student's own records, so editing or deleting a
  transaction updates the dashboard, budgets, analytics and alerts immediately.

## Project structure

Everything lives in one project folder. Only `templates/`, `static/` and `tests/` are subfolders
(Flask looks for templates and static files there).

```
monetrax/
  app.py              app factory + entry point (python app.py / gunicorn "app:create_app()")
  config.py           settings (SQLite locally, PostgreSQL via DATABASE_URL)
  extensions.py       SQLAlchemy + LoginManager
  models.py           User, Category, Transaction, Budget, SavingsGoal, SavingsContribution, Notification
  security.py         CSRF, safe redirects, security headers
  validators.py       server-side validation for every form
  utils.py            dates in the app time zone, money parsing/formatting, ownership checks

  finance.py          totals, category breakdowns, time series, budget status, savings pace,
                      wallet balances, safe to spend today
  schedule.py         recurring engine: next dates, catch-up posting, upcoming bills
  alerts.py           budget threshold (75/90/100%) and savings milestone notifications
  insights.py         rule-based Monetrax Insights

  auth.py             /login /register /forgot-password /logout
  dashboard.py        /dashboard
  transactions.py     /transactions
  recurring.py        /transactions/recurring
  wallets.py          /wallets
  budgets.py          /budgets
  savings.py          /savings
  analytics.py        /analytics
  notifications.py    /notifications
  settings.py         /settings

  templates/          base, layouts/app.html (sidebar shell), components/ (reusable macros), one folder per page
  static/             css/ (auth.css, app.css), js/ (auth.js, app.js), img/
  tests/              pytest suite
  requirements.txt  render.yaml  Procfile  .env.example  pytest.ini
```

## Logo and brand files

`static/brand/` holds the logo in every form you're likely to need:

| File | Use it for |
|---|---|
| `monetrax-logo.svg` / `monetrax-logo-white.svg` | Logo with name, on light / dark backgrounds |
| `monetrax-logo-tagline.svg` / `monetrax-logo-tagline-white.svg` | Logo with "Your money. Your direction." |
| `monetrax-mark.svg` / `monetrax-mark-emerald.svg` | App icon tile (navy / emerald) |
| `monetrax-symbol-navy.svg` / `monetrax-symbol-white.svg` | The symbol alone, no tile |
| `monetrax-icon-512.png`, `monetrax-icon-192.png` | App stores, social profiles, slides |
| `monetrax-brand-sheet.png` | Overview of all versions |

The symbol is an **M** whose last stroke rises into an arrow: your money, heading in your direction.
Inside the app the logo is redrawn as pixel art on a 16×16 grid with the name in Press Start 2P;
the files above are the smooth originals for print and app stores.
The dot is the coin you're tracking. The name is set in Plus Jakarta Sans ExtraBold, converted to
outlines so it looks the same everywhere without the font installed.

## Notes before going live
- **Database migrations:** tables are created with `db.create_all()`. Once the schema starts changing,
  add Flask-Migrate (Alembic) so existing data is migrated safely.
- **Tailwind** loads from its Play CDN. For production, compile it with the Tailwind CLI and serve the CSS.
- **Password reset** asks for an email but doesn't send one yet; connect an email provider to finish it.
- **Terms and Privacy** text in `templates/auth/register.html` is a placeholder.
- Consider rate limiting `/login` and `/register` (e.g. Flask-Limiter).
