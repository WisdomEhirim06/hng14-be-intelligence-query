# Insighta Labs - Intelligence Query Engine

This is the Stage 2 backend task for HNG (Backend Wizards). It implements advanced filtering, sorting, pagination, and a rule-based natural language query (NLQ) engine for demographic data.

## Natural Language Query (NLQ) Approach

### Logic and Keyword Mapping
The parsing logic is **rule-based** and uses regular expressions (Regex) combined with keyword dictionaries to map plain English queries to structured filters.

| Category | Keywords / Logic | Mapping |
|----------|-----------------|---------|
| **Gender** | `male`, `female`, `man`, `woman`, `boy`, `girl` | `gender` filter |
| **Age Group** | `child`, `teenager`, `adult`, `senior` | `age_group` filter |
| **"Young"** | `young` | `min_age=16` AND `max_age=24` |
| **Age Range** | `above X`, `older than X`, `below X`, `younger than X` | `min_age` or `max_age` |
# Insighta Labs+ - Secure Profile Intelligence System

Insighta Labs+ is a secure, multi-interface platform for profile intelligence, building upon the Stage 2 query engine. It features GitHub OAuth authentication, role-based access control (RBAC), a CLI tool, and a web portal.

## System Architecture

The system is composed of three primary components:
1.  **Backend (FastAPI)**: Core API handling data processing, natural language parsing, and security enforcement.
2.  **Insighta CLI**: A Python-based CLI tool for power users and engineers, using PKCE for secure authentication.
3.  **Web Portal**: A modern web interface for analysts, using HTTP-only cookies for secure session management.

## Authentication Flow

We use **GitHub OAuth 2.0 with PKCE** for secure authentication across all interfaces.

### CLI Flow (PKCE)
1.  CLI generates a `code_verifier` and `code_challenge`.
2.  Opens the browser to GitHub with the `code_challenge`.
3.  GitHub redirects to the CLI's local callback server with an authorization `code`.
4.  CLI sends the `code` and `code_verifier` to the Backend.
5.  Backend exchanges them with GitHub (using the `client_secret`) and issues Access + Refresh tokens.

### Web Flow
1.  User clicks "Login with GitHub" and is redirected to GitHub.
2.  Backend handles the callback and exchanges the code for a GitHub token.
3.  Backend issues JWT tokens and sets them as **HTTP-only cookies** in the browser.

## Token Handling

-   **Access Token**: JWT with 3-minute expiry.
-   **Refresh Token**: UUIDv7 stored in the database with 5-minute expiry.
-   **Rotation**: Refresh tokens are rotated on every use; the old token is invalidated immediately, and a new pair is issued.

## Role Enforcement Logic

We implement RBAC with two roles:
-   **Analyst (Default)**: Read-only access to profiles, search, and export.
-   **Admin**: Full access, including the ability to trigger profile creation via external APIs.
Enforcement is handled via FastAPI dependencies (`get_current_user`, `check_admin`).

## Natural Language Parsing Approach

Natural language queries (e.g., "young males from Nigeria") are parsed using a regex-based tokenization strategy in `parser.py`. It identifies:
-   Genders (male, female, etc.)
-   Age groups (child, teen, adult, senior)
-   Age comparisons (above/below X, young = 16-24)
-   Countries (mapped to ISO codes)
The parser transforms these into structured filters used by the database query builder.

## CLI Usage

Install the CLI globally:
```bash
cd insighta-cli && pip install -e .
```
Commands:
- `insighta login` / `insighta logout`
- `insighta list --gender male --country NG`
- `insighta search "young females"`
- `insighta create --name "Harriet Tubman"`

## API Versioning

All API requests must include the header:
`X-API-Version: 1`
Responses follow a standardized pagination shape:
```json
{
  "status": "success",
  "page": 1,
  "total": 2026,
  "links": { "self": "...", "next": "...", "prev": null },
  "data": [...]
}
```

## Testing & Grading

To facilitate automated grading, this system supports a `test_code` bypass in the OAuth callback:
1.  **Endpoint**: `GET /auth/github/callback?code=test_code`
2.  **Behavior**: Returns a JSON response with `access_token` and `refresh_token` for a seeded **Admin** user.
3.  **Use Case**: Allows the grader bot to verify role enforcement and token rotation without requiring a live GitHub interaction.

## Tech Stack
- **FastAPI** — High-performance web framework.
- **Psycopg2** — Direct PostgreSQL interaction for Supabase compatibility.
- **Vercel** — Serverless deployment runtime.
- **UUID v7** — Next-gen sortable unique identifiers.
