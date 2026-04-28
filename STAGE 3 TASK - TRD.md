# **Backend Engineering Track**

## **Stage 3 – Insighta Labs+: Secure Access & Multi-Interface Integration**

---

## **Context**

You are now part of the backend team at **Insighta Labs**.

In previous stages, you built the **Profile Intelligence System**:

* Data collection from external APIs  
* Structured storage in a database  
* Advanced querying (filtering, sorting, pagination)  
* Natural language search

At this point, your system is functional.

---

## **Important Note**

This stage builds directly on **Stage 2**.

Everything implemented in Stage 2 must continue to work:

* Filtering  
* Sorting  
* Pagination  
* Natural language querying

No regressions are allowed.

---

## **Your New Responsibility**

You have been appointed as the **Lead Developer on Insighta Labs+**, an internal initiative to transform the current system into a **secure, accessible platform for real users**.

This is now a **product used by multiple teams**:

* Analysts (non-technical users)  
* Engineers and power users  
* Internal stakeholders

---

## **The Problem**

Despite having a functional system, there are critical gaps:

* No authentication: anyone can access the system  
* No user ownership: actions are not tied to identities  
* No access control: all users have the same permissions  
* No real interface: only direct API access exists

This makes the system:

* Unsafe  
* Unscalable  
* Unusable for real teams

---

## **Objective**

Upgrade the system into a **secure, multi-interface platform**.

You will:

* Add authentication  
* Introduce user roles (Role-based access control)  
* Secure all endpoints  
* Build a CLI tool  
* Build a simple web portal  
* Ensure consistency across all interfaces

---

## **Expected Outcome**

At the end of this stage, Insighta Labs+ should:

* Require authentication for all access  
* Support login via GitHub OAuth  
* Issue and manage secure sessions (access \+ refresh tokens)  
* Enforce role-based permissions across all endpoints  
* Be accessible through:  
  * A CLI tool  
  * A Web portal  
* Maintain a single source of truth across all interfaces

---

## **System Requirements**

You are responsible for building and integrating **three parts**:

### **A- CLI Authentication Flow**

Expected behavior:

1. User runs:  
   insighta login  
2. CLI:  
   * Generates:  
     * `state` (request validation)  
     * `code_verifier` (PKCE secret)  
     * `code_challenge` (derived value)  
   * Starts a temporary local callback server  
   * Opens the GitHub OAuth page in the browser  
3. User authenticates via GitHub  
4. GitHub redirects to:  
   http://\<server\>:\<port\>/callback  
5. CLI:  
   * Captures the callback  
   * Validates the `state`  
   * Sends `code + code_verifier` to your backend  
6. Backend:  
   * Exchanges the code with GitHub  
   * Retrieves user information  
   * Creates or updates the user  
   * Issues:  
     * Access token  
     * Refresh token  
7. CLI:  
   * Stores tokens locally  
   * Confirms login:  
     * Logged in as @username

### **B- Web Authentication Flow**

* User clicks “Continue with GitHub”  
* OAuth handled directly in browser  
* Backend processes callback  
* User session is established

---

## **1\. Authentication System (Backend Core)**

You must implement a **secure OAuth flow using GitHub with PKCE**.

---

#### **Auth Endpoints**

##### **`GET /auth/github`**

* Redirects user to GitHub OAuth

---

##### **`GET /auth/github/callback`**

* Handles OAuth callback  
* Creates or retrieves user  
* Issues tokens

---

##### **`POST /auth/refresh`**

**Request**

{  
  "refresh\_token": "string"  
}

**Response**

{  
  "status": "success",  
  "access\_token": "string",  
  "refresh\_token": "string"  
}

- The old refresh token must be invalidated immediately after use. Each refresh issues a new pair.

---

##### **`POST /auth/logout`**

**Behavior**

* Invalidates the refresh token server-side

---

#### **Token Expiry**

| Token | Expiry |
| ----- | ----- |
| Access token | 3 minutes |
| Refresh token | 5 minutes |

---

#### **User System**

Create a users table with:

| Field | Type | Notes |
| ----- | ----- | ----- |
| id | UUID v7 | Primary key |
| github\_id | VARCHAR | Unique |
| username | VARCHAR |  |
| email | VARCHAR |  |
| avatar\_url | VARCHAR |  |
| role | VARCHAR | `admin` or `analyst` |
| is\_active | BOOLEAN | If `false` → 403 Forbidden on all requests |
| last\_login\_at | TIMESTAMP |  |
| created\_at | TIMESTAMP |  |

---

#### **Roles**

* **admin** \- Full access: can create and delete profiles, query  
* **analyst** \- Read-only: can only read and search

Default role: **analyst**

---

#### **Access Control**

All `/api/*` endpoints must:

* Require authentication  
* Enforce role permissions

Do not implement scattered checks; use a structured approach.

---

### **2️⃣ Profile APIs (Updates)**

---

#### **API Versioning (Required)**

All profile-related endpoints must include this header:

X-API-Version: 1

Requests without this header must be rejected:

{  
  "status": "error",  
  "message": "API version header required"  
}

Status: `400 Bad Request`

---

#### **Pagination Update**

All paginated responses must now include:

{  
  "status": "success",  
  "page": 1,  
  "limit": 10,  
  "total": 2026,  
  "total\_pages": 203,  
  "links": {  
    "self": "/api/profiles?page=1\&limit=10",  
    "next": "/api/profiles?page=2\&limit=10",  
    "prev": null  
  },  
  "data": \[ ... \]  
}

Applies to:

* `GET /api/profiles`  
* `GET /api/profiles/search`

---

#### **Create Profile (Admin Only)**

##### **`POST /api/profiles`**

**Request**

{  
  "name": "Harriet Tubman"  
}

**Behavior**

* Calls external APIs (Stage 1 logic)  
* Transforms data  
* Stores in database  
* Returns saved profile

**Response**

{  
  "status": "success",  
  "data": {  
    "id": "uuid",  
    "name": "Harriet Tubman",  
    "gender": "female",  
    "gender\_probability": 0.97,  
    "age": 28,  
    "age\_group": "adult",  
    "country\_id": "US",  
    "country\_name": "United States",  
    "country\_probability": 0.89,  
    "created\_at": "timestamp"  
  }  
}

---

#### **Export Profiles (CSV)**

##### **`GET /api/profiles/export?format=csv`**

**Behavior**

* Applies the same filters as `GET /api/profiles`  
* Supports sorting params  
* Returns a CSV file

**Response**

* `200 OK`  
* `Content-Type: text/csv`  
* `Content-Disposition: attachment; filename="profiles_<timestamp>.csv"`

**CSV columns (in order):**

id, name, gender, gender\_probability, age, age\_group, country\_id, country\_name, country\_probability, created\_at

**Delimiter**:,

---

### **3️⃣ CLI Application**

You must build a CLI tool that interacts with the APIs.

---

#### **Installation Requirement**

The CLI must be installable and usable globally.

After installation:

insighta login

must work from any directory.

---

#### **Commands**

**Auth**

insighta login  
insighta logout  
insighta whoami

**Profiles**

insighta profiles list  
insighta profiles list \--gender male  
insighta profiles list \--country NG \--age-group adult  
insighta profiles list \--min-age 25 \--max-age 40  
insighta profiles list \--sort-by age \--order desc  
insighta profiles list \--page 2 \--limit 20

insighta profiles get \<id\>

insighta profiles search "young males from nigeria"

insighta profiles create \--name "Harriet Tubman"

insighta profiles export \--format csv  
insighta profiles export \--format csv \--gender male \--country NG

---

#### **CLI Expectations**

* Uses authentication tokens on every request  
* Stores credentials at `~/.insighta/credentials.json`  
* Handles token expiry — auto-refresh if possible, prompt re-login if not  
* Displays results as a structured table with a loader while fetching  
* Provides feedback during operations (loading states)  
* Handles errors clearly  
* Saves exported CSV to the current working directory

---

### **4️⃣ Web Portal**

Build a simple, functional interface for non-technical users.

---

#### **Required Pages**

* Login (GitHub OAuth)  
* Dashboard (basic metrics)  
* Profiles list (filters \+ pagination)  
* Profile detail view  
* Search page  
* Account page

---

#### **Authentication (Web Portal)**

* Use **HTTP-only cookies**  
* Tokens must not be accessible via JavaScript  
* Include CSRF protection

### **Expectations**

* Uses same backend APIs as CLI  
* Reflects real-time data  
* Enforces authentication and roles

---

### **5️⃣ System Consistency**

All features must behave the same across:

* API  
* CLI  
* Web portal

---

### **6️⃣ Rate Limiting & Logging**

---

#### **Rate Limiting**

| Scope | Limit |
| ----- | ----- |
| Auth endpoints (`/auth/*`) | 10 requests / minute |
| All other endpoints | 60 requests / minute per user |

Return `429 Too Many Requests` when exceeded.

---

#### **Logging**

Log on every request:

* Method  
* Endpoint  
* Status code  
* Response time

---

### **7️⃣ Architecture & Deployment**

---

#### **Repositories**

Structure your system into three repositories:

* Backend  
* CLI  
* Web portal

---

#### **Deployment**

* Backend must be publicly accessible  
* Web portal must be deployed and accessible  
* CLI runs locally

---

### **8️⃣ Engineering Standards**

---

#### **Commits**

Use conventional commits with scope:

e.g.:

feat(auth): add github oauth  
fix(cli): handle token refresh

---

#### **Branches**

Follow clear naming conventions.

---

#### **Pull Requests**

* PRs must be used before merging to `main`

---

#### **CI/CD**

All repositories must have GitHub Actions that run on PR to `main`:

* Linting  
* Tests  
* Build checks (where applicable)

---

### **9️⃣ Additional Requirements**

* Use environment variables (`.env`)  
* Do not hardcode API URLs  
* Standardize error responses:

{  
  "status": "error",  
  "message": "message"  
}

---

## **Grading Structure**

Total Score: **100 Points**

To pass Stage 3, you must score at least **75/100**.

| Criteria | Points |
| ----- | ----- |
| Authentication & PKCE flow | 20 |
| Role enforcement | 10 |
| CLI (commands \+ rich output \+ token handling) | 20 |
| Web portal (pages \+ HTTP-only cookies) | 15 |
| API updates (versioning, pagination, export) | 10 |
| Rate limiting & logging | 5 |
| CI/CD setup | 5 |
| Engineering standards (commits, PRs, branches) | 5 |
| README completeness | 10 |
| **Total** | **100** |

---

**System Expectations**

The system must behave as a **unified platform**:

* CLI and Web share the same backend  
* Data is consistent across interfaces  
* Authentication is enforced globally  
* Access control is reliable and predictable

---

**Key Engineering Challenges**

You are expected to handle:

* OAuth with PKCE across CLI and browser  
* CLI ↔ browser ↔ backend coordination  
* Token lifecycle management (access \+ refresh)  
* Role-based authorization design  
* Multi-interface consistency  
* Failure handling (expired tokens, failed auth, timeouts)

---

**Submission Requirements**

You must submit:

* Backend repository  
* CLI repository  
* Web portal repository  
* Live backend URL  
* Live web portal URL

---

### **README must include:**

* System architecture  
* Authentication flow  
* CLI usage  
* Token handling approach  
* Role enforcement logic  
* Natural language parsing approach

---

# **Evaluation Criteria**

Evaluation will be based on:

* System design quality  
* Security implementation  
* Consistency across components  
* Handling of edge cases  
* Code quality  
* Clarity of explanations during demo

# **What This Stage Tests**

This stage evaluates whether you can:

* Extend an existing system into a real product  
* Design for multiple types of users  
* Implement secure authentication flows  
* Maintain consistency across different interfaces  
* Think beyond features and focus on systems

