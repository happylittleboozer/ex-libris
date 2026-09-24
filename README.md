# Ex Libris

Staff admin for a lending library. Librarians catalogue books and record loans. Members do not get an account.

## Demo logins

| User | Password | What they can do |
| --- | --- | --- |
| `librarian` | `exlibris-local` | Superuser. Full catalogue, plus Users and Groups. |
| `staff` | `exlibris-local` | View authors, books, members, and loans. Cannot add, edit, delete, or mark loans returned. |

A Google sign-in creates a Staff user. It does not create an admin. Promoting someone is a manual change of their group.

## Lending rules

A loan is refused when every copy of the book is already out, or when the member already has 5 open loans. An open loan is one with no return time. Recording a return sets that time once, and a later edit cannot change it. Overdue is not stored: it is a loan that is still out and whose due date is before today. Due today is still open.

"Today" is the library's day in Europe/Tallinn. The desk is in Estonia, and Django's `TIME_ZONE` is that zone, so every account shares one clock when the overdue list is built. Detecting the signed-in user's timezone was left out. The browser zone is not read, and users have no timezone field. A librarian elsewhere would otherwise see a different overdue set for the same loans.

## Run locally

Python 3.14, then:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_library
python manage.py runserver
```

Open http://127.0.0.1:8000/admin/. Put real values in `.env`. That file is not committed. `.env.example` lists every name.

Google sign-in needs this redirect on the OAuth client: `http://127.0.0.1:8000/accounts/google/login/callback/`.

## Environment

| Name | Where it is set |
| --- | --- |
| `DEBUG` | `true` locally. Render blueprint sets `false`. |
| `SECRET_KEY` | Required when `DEBUG` is off. Render asks for it. |
| `DATABASE_URL` | Neon pooled URL. Local `.env` uses the dev branch. Render should use main. |
| `ALLOWED_HOSTS` | Local default is `localhost,127.0.0.1`. On Render, the service host. |
| `CSRF_TRUSTED_ORIGINS` | Empty locally. On Render, `https://<service>.onrender.com`. |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_ENDPOINT_URL`, `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_CUSTOM_DOMAIN` | Cloudflare R2. Covers are public objects. Production refuses to boot if any of these are missing. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Both must be set or the Google button stays hidden. |
| `GEMINI_API_KEY` | Form assistant. If it is missing or the call fails, the form still saves. |

A session lasts 8 hours. In production the session cookie is HTTPS-only.

## Reseed

`python manage.py seed_library` deletes the catalogue and the two demo users, then loads the same set again: 60 authors, 200 books with covers, 120 members, 300 returned loans, 150 open loans, 50 overdue loans. Sign in again afterwards. The password above is unchanged.

On Render, open the service shell and run the same command. That writes to whichever database `DATABASE_URL` points at.

## Why this stack

### Framework

Django 5.2 and Django Admin. The brief asks for an admin the framework generates: search, filters, inlines, a bulk action, and field help text. Auth, migrations, sessions, and CSRF come with the same project. Loan rules live on the model, and the admin calls them.

Laravel with Filament was the PHP alternative. Filament has filters, relation managers, and bulk actions, and a form schema would feed the assistant. It was set aside because the pairing would then be in PHP, and the admin would be a package to keep aligned with the schema rather than the framework's own admin.

Rails with ActiveAdmin and Devise was the Ruby alternative. ActiveAdmin covers filters and batch actions. It was set aside because the language to defend here is Python, and ActiveAdmin's DSL makes it easy to hide a lending rule inside the admin class.

A separate single-page app was not built. The brief asks for a generated admin, and there is no public site in front of it. A second frontend would repeat the catalogue screens and add another login.

### Database

Neon Postgres in Frankfurt, on the pooled connection. The app is in the same region, and a pooled host must not keep a Django connection open across requests. If `DATABASE_URL` is missing when debug mode is off, the process refuses to start rather than open a local database. Tests use SQLite in memory so a test run never writes to Neon.

Supabase Postgres is the same engine with a clearer table browser. It was set aside because the rest of that product invites a second login system beside Django.

Postgres on Render or Railway would put the database next to the app and shorten setup. It was set aside because the free-tier limits and backups then belong to the host, and Neon can sit in Frankfurt beside the app without that coupling.

### Object storage

Cloudflare R2, through django-storages and the S3 API. Covers are public objects. The database stores the object key. A file on the server disk would vanish on the next deploy and would not be shared by a second instance.

Backblaze B2 uses the same S3 client and a generous free tier. It was set aside because publishing a file from B2 takes more setup than R2's public bucket URL.

Amazon S3 is the API the storage libraries assume. It was set aside because IAM and the free tier are easier to step outside of for a demo catalogue.

### Hosting

Render, a free web service in Frankfurt. It provides HTTPS, environment variables, and a cold start the brief already accepts. Gunicorn serves the app. WhiteNoise serves the admin's CSS. `DEBUG` is off. Secrets stay in the environment.

Fly.io can run more than one machine, which is the honest answer to more traffic, and that is also why covers cannot live on local disk. It was set aside because a new account's free allowance is a short trial, and the brief can be finished without a card.

Railway can create the app and Postgres in one project. It was set aside because the ongoing free allowance is about a dollar a month, which will not keep this process up, and the plan may ask for a card.

### Assistant

Gemini 3.5 Flash-Lite. The book and loan forms send that model's labels, help text, and choices, and the question, capped at 500 characters. A missing key, a timeout, or an API error shows a fixed message, and the form still saves. Google's free tier may use those prompts to improve Google's products. That is acceptable for this demo catalogue.

Gemini 3.7 Flash was the larger Google option. It was set aside because the prompt already contains the help text, so a Flash-Lite model is enough.

Groq, with a small open model, answers quickly and speaks the OpenAI API shape. It was set aside because the free daily token budget is a hard ceiling, and a reviewer clicking around can hit a rate limit.

OpenRouter can point one client at whatever free model is available. It was set aside because those free routes move or rate-limit without notice.

A self-hosted model was left out. A GPU, or a model on the same free web service, would spend the time the lending rules and the admin need.

### Auth

Django's password hasher, sessions, and groups. Staff can view the catalogue. Admin can change it. The seeded librarian is also a superuser, so a reviewer can open Users and Groups and see the difference. Sessions last 8 hours and are HTTPS-only in production.

Google sign-in, through django-allauth, is the bonus login. A new Google user joins Staff. The button is hidden until both client settings exist.

GitHub sign-in was the lighter OAuth setup: a free OAuth app and less consent-screen work. It was set aside in favour of Google, which is the login a reviewer is more likely to already have. The role rule would have been the same.

### Monitoring

No error tracker and no metrics. This is a small admin for a review, and Render's process list is enough to see that the site is up. A monitoring account would add another secret for a service that is not on call.

### Logging

No log pipeline. Django writes to the process output, which Render keeps. A failed assistant call logs the exception type and nothing else. A shipping pipeline would matter once someone is responsible for the site overnight.

### CI/CD

No workflow runs the tests or deploys the app. `render.yaml` is the service definition Render uses once the service exists: install dependencies, collect static files, migrate, then start gunicorn. The suite is run locally with `python manage.py test`, against SQLite. A GitHub Actions pipeline was left out. This is a single-person review, the checks already run on the machine that has the code, and a hosted job that reached Neon or R2 would store those secrets a second time.

## What was left out

Waitlists, renewals, fines, and email reminders. Each one is a second product. A waitlist would also change the lending rule: a returned copy might already be promised to someone else.

## With more time

A waitlist would be first, because it changes who may borrow a returned copy. After that, error reporting on the Render service, then renewal of an open loan by moving the due date once.
