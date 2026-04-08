#  Examination Middleware (LMS-SAE Bridge)

![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104.1-009688.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-14%2B-336791.svg)
![Moodle](https://img.shields.io/badge/Integration-Moodle%20LMS-orange)

**Examination Middleware** is a robust, secure, and automated bridge designed to streamline the digitization and submission of physical examination answer sheets to the Moodle Learning Management System (LMS). It acts as an intelligent intermediary between the physical examination hall and the digital grading environment.

---

## ⚠️ Recent updates (2026-01-12)

The codebase has received several maintenance and UX updates to improve safety, auditing and staff workflows. Highlights:

- New maintenance scripts:
   - `setup_username_reg.py` — upsert a single Moodle `username -> register_number` mapping. Useful to seed or correct mappings used during student login and pending-list authorization. Example:

      ```bash
      # interactive
      python setup_username_reg.py

      # direct
      python setup_username_reg.py --username 22007928 --register 212222240047
      ```

   - `setup_subject_mapping.py` — interactive workflow to find an assignment by course-module-id (CMID) in Moodle, create or update a `SubjectMapping`, and optionally fix existing artifacts that reference the wrong assignment id.

- Staff UI changes:
   - `app/templates/staff_upload.html` now contains a Reports modal (view/resolve/edit/delete reports) and improved listing behaviour.
   - The `Total Uploaded` stat is computed from the visible (non-deleted) artifacts returned by the listing endpoint, so the navbar count now matches the visible table ("Showing X of Y files").
   - Client-side behaviour was hardened: the student/staff login flows no longer call `localStorage.clear()`; only session keys are removed on logout.

- Backend/service changes (important for deploy and troubleshooting):
   - `app/services/artifact_service.py` was hardened to explicitly catch `IntegrityError` on DB flush/commit and to rollback safely. This reduces silent failures for duplicate transaction IDs.
   - `get_pending_for_student()` requires either a valid 12-digit `register_number` OR both `moodle_user_id` and `moodle_username`. This prevents ambiguous or leaking results when student identity is unclear.
   - Admin remediation: if a deterministic `transaction_id` collides with an existing (deleted/archived) artifact, clearing or nulling the `transaction_id` in the DB row will allow a re-upload. Use the `audit_logs` and `ExaminationArtifact` table to locate problematic rows before manual edits.

- API and client notes:
   - Staff UI attempts multiple common listing endpoints (e.g. `/api/upload/all`, `/upload/all`, `/api/artifacts`) to be resilient against different backend deployments. Prefer endpoints that return an array of `artifacts` for best UI compatibility.
   - Consider returning HTTP 409 for DB integrity conflicts (duplicate transaction / unique constraint) so the client can surface a clear message instead of a generic 500.

---


##  The Problem Statement

In academic institutions transitioning to digital grading, handling physical answer scripts presents significant logistical challenges:

1.  **Manual Labor**: Individually scanning, renaming, and uploading hundreds of answer scripts to specific Moodle assignments is time-consuming and inefficient.
2.  **Human Error**: Manual processes are prone to errors such as uploading the wrong file to a student's profile or mislabeling files.
3.  **Security & Integrity**: Direct database manipulation or unverified bulk uploads can compromise the chain of custody.
4.  **Student Verification**: Students often lack a mechanism to verify that their specific physical paper was scanned and submitted correctly before grading begins.

##  Proposed Solution & Architecture

This middleware solves these issues by decoupling the **scanning/uploading** process from the **submission** process, introducing a secure validation layer.

### Core Concept
The system utilizes a **3-Step "Upload-Verify-Push" Workflow**:
1.  **Bulk Ingestion**: Administrative staff upload bulk batches of scanned PDF/Images.
2.  **Intelligent Processing**: The system parses filenames (e.g., `123456_MATH101.pdf`) to extract the Student Register Number and Subject Code, automatically mapping them to the correct Moodle Assignment ID.
3.  **Student-Led Submission**: Students log in using their Moodle credentials. They view *only* their specific answer scripts and trigger the final submission to Moodle. This ensures non-repudiation and student verification.

### High-Level Architecture

```mermaid
graph LR
    A[Physical Scans] -->|Bulk Upload| B(Staff Portal / Middleware)
    B -->|Parse & Store| C{PostgreSQL DB}
    D[Student] -->|Login via Moodle Creds| E(Student Portal)
    E -->|Fetch Pending Papers| C
    E -->|Trigger Submission| F[Moodle LMS]
    F -->|Token Exchange| E
```
## Database Schema Overview

The database is designed for data integrity and auditability. Key models include:

| Model | Description |
| :--- | :--- |
| **`ExaminationArtifact`** | The core entity representing a scanned paper. Stores UUID, file path, hash (SHA-256), extracted metadata (Reg No, Subject), and current `WorkflowStatus` (e.g., `PENDING`, `SUBMITTED_TO_LMS`). |
| **`SubjectMapping`** | Configuration table mapping a Subject Code (e.g., `19AI405`) to a specific Moodle Course ID and Assignment ID. |
| **`StaffUser`** | Accounts for administrative staff authorized to perform bulk uploads. |
| **`StudentSession`** | Manages ephemeral student sessions. Stores encrypted Moodle access tokens used to perform submissions on behalf of the student. |
| **`AuditLog`** | A rigid ledger tracking every action (Upload, View, Submit) with IP addresses and timestamps to ensure a chain of custody. |
| **`SubmissionQueue`** | A buffer for handling Moodle API failures or maintenance windows, ensuring no submission is lost. |

---

## Database tables created by `init_db.py`

When you run `python init_db.py` it executes SQLAlchemy's `Base.metadata.create_all()` which creates the database tables defined in `app/db/models.py`. On PostgreSQL, the necessary sequences for integer primary keys are created automatically.

The `init_db.py` script seeds minimal configuration (default admin user, subject mappings, system config). If you run with the `--seed-samples` flag it will also add a sample artifact and `report_issue` audit log useful for local testing.

Below is the full list of tables and sequences that should be present after running `init_db.py` (example `\d` output):

```
 public | audit_logs                       | table    | postgres
 public | audit_logs_id_seq                | sequence | postgres
 public | examination_artifacts            | table    | postgres
 public | examination_artifacts_id_seq     | sequence | postgres
 public | staff_users                      | table    | postgres
 public | staff_users_id_seq               | sequence | postgres
 public | student_sessions                 | table    | postgres
 public | student_sessions_id_seq          | sequence | postgres
 public | student_username_register        | table    | postgres
 public | student_username_register_id_seq | sequence | postgres
 public | subject_mappings                 | table    | postgres
 public | subject_mappings_id_seq          | sequence | postgres
 public | submission_queue                 | table    | postgres
 public | submission_queue_id_seq          | sequence | postgres
 public | system_config                    | table    | postgres
 public | system_config_id_seq             | sequence | postgres
```

If any of these tables are missing after running `init_db.py`:

- Ensure your `DATABASE_URL` is set and points to the database you initialized.
- Confirm the DB user has privileges to create tables in the `public` schema.
- Check `init_db.py` output for errors and fix any import or connection issues before re-running.

For production deployments we strongly recommend using Alembic for schema migrations instead of `create_all()` so you can evolve the schema safely across releases.

## Detailed schema (information_schema.columns)

Below is a dump of `information_schema.columns` for the `public` schema taken from a development database. It lists every table, column, data type, nullability and default value. This is useful for developers who want to inspect the actual physical schema created by `init_db.py`.

```
audit_logs                | id                     | integer                  | NO          | nextval('audit_logs_id_seq'::regclass)
audit_logs                | action                 | character varying        | NO          |
audit_logs                | action_category        | character varying        | NO          |
audit_logs                | description            | text                     | YES         |
audit_logs                | actor_type             | character varying        | NO          |
audit_logs                | actor_id               | character varying        | YES         |
audit_logs                | actor_username         | character varying        | YES         |
audit_logs                | actor_ip               | character varying        | YES         |
audit_logs                | artifact_id            | integer                  | YES         |
audit_logs                | target_type            | character varying        | YES         |
audit_logs                | target_id              | character varying        | YES         |
audit_logs                | request_data           | jsonb                    | YES         |
audit_logs                | response_data          | jsonb                    | YES         |
audit_logs                | error_details          | jsonb                    | YES         |
audit_logs                | moodle_api_function    | character varying        | YES         |
audit_logs                | moodle_response_code   | integer                  | YES         |
audit_logs                | created_at             | timestamp with time zone | YES         | now()
examination_artifacts     | id                     | integer                  | NO          | nextval('examination_artifacts_id_seq'::regclass)
examination_artifacts     | artifact_uuid          | uuid                     | NO          |
examination_artifacts     | raw_filename           | character varying        | NO          |
examination_artifacts     | original_filename      | character varying        | NO          |
examination_artifacts     | parsed_reg_no          | character varying        | YES         |
examination_artifacts     | parsed_subject_code    | character varying        | YES         |
examination_artifacts     | file_blob_path         | character varying        | NO          |
examination_artifacts     | file_hash              | character varying        | NO          |
examination_artifacts     | file_size_bytes        | bigint                   | YES         |
examination_artifacts     | mime_type              | character varying        | YES         |
examination_artifacts     | moodle_user_id         | bigint                   | YES         |
examination_artifacts     | moodle_username        | character varying        | YES         |
examination_artifacts     | moodle_course_id       | integer                  | YES         |
examination_artifacts     | moodle_assignment_id   | integer                  | YES         |
examination_artifacts     | workflow_status        | USER-DEFINED             | NO          |
examination_artifacts     | moodle_draft_item_id   | bigint                   | YES         |
examination_artifacts     | moodle_submission_id   | character varying        | YES         |
examination_artifacts     | lms_transaction_id     | character varying        | YES         |
examination_artifacts     | transaction_id         | character varying        | YES         |
examination_artifacts     | uploaded_at            | timestamp with time zone | YES         | now()
examination_artifacts     | validated_at           | timestamp with time zone | YES         |
examination_artifacts     | submit_timestamp       | timestamp with time zone | YES         |
examination_artifacts     | completed_at           | timestamp with time zone | YES         |
examination_artifacts     | uploaded_by_staff_id   | integer                  | YES         |
examination_artifacts     | submitted_by_user_id   | bigint                   | YES         |
examination_artifacts     | transaction_log        | jsonb                    | YES         |
examination_artifacts     | error_message          | text                     | YES         |
examination_artifacts     | retry_count            | integer                  | YES         |
staff_users               | id                     | integer                  | NO          | nextval('staff_users_id_seq'::regclass)
staff_users               | username               | character varying        | NO          |
staff_users               | email                  | character varying        | NO          |
staff_users               | hashed_password        | character varying        | NO          |
staff_users               | full_name              | character varying        | YES         |
staff_users               | role                   | character varying        | YES         |
staff_users               | is_active              | boolean                  | YES         |
staff_users               | created_at             | timestamp with time zone | YES         | now()
staff_users               | last_login_at          | timestamp with time zone | YES         |
student_sessions          | id                     | integer                  | NO          | nextval('student_sessions_id_seq'::regclass)
student_sessions          | session_id             | character varying        | NO          |
student_sessions          | moodle_user_id         | bigint                   | NO          |
student_sessions          | moodle_username        | character varying        | NO          |
student_sessions          | moodle_fullname        | character varying        | YES         |
student_sessions          | encrypted_token        | text                     | NO          |
student_sessions          | token_expires_at       | timestamp with time zone | YES         |
student_sessions          | ip_address             | character varying        | YES         |
student_sessions          | user_agent             | character varying        | YES         |
student_sessions          | created_at             | timestamp with time zone | YES         | now()
student_sessions          | last_activity_at       | timestamp with time zone | YES         | now()
student_sessions          | expires_at             | timestamp with time zone | NO          |
student_sessions          | register_number        | character varying        | YES         |
student_username_register | id                     | integer                  | NO          | nextval('student_username_register_id_seq'::regclass)
student_username_register | moodle_username        | character varying        | NO          |
student_username_register | register_number        | character varying        | NO          |
student_username_register | created_at             | timestamp with time zone | YES         | now()
student_username_register | updated_at             | timestamp with time zone | YES         |
subject_mappings          | id                     | integer                  | NO          | nextval('subject_mappings_id_seq'::regclass)
subject_mappings          | subject_code           | character varying        | NO          |
subject_mappings          | subject_name           | character varying        | YES         |
subject_mappings          | moodle_course_id       | integer                  | NO          |
subject_mappings          | moodle_course_idnumber | character varying        | YES         |
subject_mappings          | moodle_assignment_id   | integer                  | NO          |
subject_mappings          | moodle_assignment_name | character varying        | YES         |
subject_mappings          | exam_session           | character varying        | YES         |
subject_mappings          | is_active              | boolean                  | YES         |
subject_mappings          | created_at             | timestamp with time zone | YES         | now()
subject_mappings          | updated_at             | timestamp with time zone | YES         |
subject_mappings          | last_verified_at       | timestamp with time zone | YES         |
submission_queue          | id                     | integer                  | NO          | nextval('submission_queue_id_seq'::regclass)
submission_queue          | artifact_id            | integer                  | NO          |
submission_queue          | status                 | character varying        | YES         |
submission_queue          | priority               | integer                  | YES         |
submission_queue          | retry_count            | integer                  | YES         |
submission_queue          | max_retries            | integer                  | YES         |
submission_queue          | next_retry_at          | timestamp with time zone | YES         |
submission_queue          | queued_at              | timestamp with time zone | YES         | now()
submission_queue          | processed_at           | timestamp with time zone | YES         |
submission_queue          | last_error             | text                     | YES         |
system_config             | id                     | integer                  | NO          | nextval('system_config_id_seq'::regclass)
system_config             | key                    | character varying        | NO          |
system_config             | value                  | text                     | YES         |
system_config             | value_type             | character varying        | YES         |
system_config             | description            | text                     | YES         |
system_config             | updated_at             | timestamp with time zone | YES         |
```

This listing is provided for convenience—your actual schema may differ slightly depending on the database version and any future schema changes. Always inspect your database with `\d` (psql) or `information_schema.columns` when debugging.


## 🔄 Workflow of the Platform

### Phase 1: Administration & Setup
1.  **Mapping**: Admin configures the `SubjectMapping` table (e.g., Subject `CS101` targets Moodle Assignment `ID: 55`).
2.  **Scanning**: Examination cell scans answer sheets using the naming convention: `{RegisterNumber}_{SubjectCode}.pdf`.

### Phase 2: Staff Operations
1.  **Login**: Staff logs into the Staff Portal.
2.  **Bulk Upload**: Staff drags and drops folders of scanned files.
3.  **Validation**: The system instantly validates filenames. Invalid files are rejected; valid files are hashed and stored as `ExaminationArtifacts` with status `PENDING`.

### Phase 3: Student Operations
1.  **Login**: Student logs into the Student Portal using their university Moodle username and password.
2.  **Dashboard**: The system displays all papers tagged with their Register Number.
3.  **Review**: Student previews the PDF to ensure it is their paper.
4.  **Submit**: Student clicks "Submit".
    * *Backend Action*: The system authenticates with Moodle using the student's token.
    * *Backend Action*: Uploads the file to Moodle's draft area.
    * *Backend Action*: Finalizes the submission for grading.
5.  **Confirmation**: The status updates to `SUBMITTED_TO_LMS`.
   
## 📋 Prerequisites

- Python 3.10+
- PostgreSQL 14+
- Moodle LMS with Web Services enabled
- Redis (optional, for background tasks)

## Quick Start

### 1. Clone and Setup

```bash
cd exam_middleware
```

### 2. Create Virtual Environment

```bash
python -m venv venv

# Windows
.\venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment

Copy `.env.example` to `.env` and update the values:

```bash
copy .env.example .env
```

Edit `.env` with your settings:

```env
# Database
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/exam_middleware

# Security
SECRET_KEY=your-super-secret-key-change-in-production
ENCRYPTION_KEY=your-32-byte-encryption-key-here

# Moodle Configuration
MOODLE_BASE_URL=https://your-moodle-site.com
MOODLE_ADMIN_TOKEN=your-admin-token

# Subject Mappings (subject_code:assignment_id)
SUBJECT_ASSIGNMENT_MAP=19AI405:4,19AI411:6,ML:2
```

### 5. Setup PostgreSQL Database

```bash
# Create database
psql -U postgres -c "CREATE DATABASE exam_middleware;"
```

### Developer setup (recommended)

These additional steps make it easy for a new developer to get a working local environment.

1. Create a dedicated DB role and grant privileges (run in psql as a superuser):

```sql
-- Replace <devuser> and <devpassword>
CREATE ROLE devuser WITH LOGIN PASSWORD '<devpassword>';
CREATE DATABASE exam_middleware OWNER devuser;
GRANT ALL PRIVILEGES ON DATABASE exam_middleware TO devuser;
\c exam_middleware
GRANT ALL PRIVILEGES ON SCHEMA public TO devuser;
```

2. Export a `DATABASE_URL` for local development (example):

```powershell
$env:DATABASE_URL = 'postgresql+asyncpg://devuser:<devpassword>@localhost:5432/exam_middleware'
# Linux/macOS
export DATABASE_URL='postgresql+asyncpg://devuser:<devpassword>@localhost:5432/exam_middleware'
```

3. Create a virtualenv and install dependencies:

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate
pip install -r requirements.txt
```

4. Initialize the database (creates tables and seeds minimal config):

```bash
python init_db.py
```

5. Seed optional sample data (useful for manual testing):

```bash
python init_db.py --seed-samples
```

6. Run the app with a production-like server during development:

```bash
# Use uvicorn directly (recommended in dev)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Notes:
- The project uses `Base.metadata.create_all` in `init_db.py` to create tables. For production, use Alembic migrations instead of `create_all`.
- Replace placeholder passwords and secrets in `.env.example` before use; never commit real secrets to git.
- Consider running the app behind a reverse-proxy (nginx) and enabling TLS for production.

### 6. Initialize Database

```bash
python init_db.py
```

This will:
- Create all required tables
- Create default admin user (username: `admin`, password: `admin123`)
- Seed subject-to-assignment mappings
- Configure system settings

### 7. Run the Application

```bash
python run.py
```

The server will start at `http://localhost:8000`

## 🔗 Access Points

| Portal | URL |
|--------|-----|
| Staff Upload Portal | http://localhost:8000/portal/staff |
| Student Portal | http://localhost:8000/portal/student |
| API Documentation | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| Health Check | http://localhost:8000/health |

## 📁 File Naming Convention

Uploaded files must follow this naming pattern:

```
{RegisterNumber}_{SubjectCode}.{extension}
```

**Examples:**
- `611221104088_19AI405.pdf`
- `611221104089_ML.jpg`
- `611221104090_19AI411.png`

**Rules:**
- Register Number: Exactly 12 digits
- Subject Code: 2-10 alphanumeric characters
- Extensions: pdf, jpg, jpeg, png

## 🔐 Authentication

### Staff Authentication
- Username/password-based JWT authentication
- Default credentials: `admin` / `admin123`
- Token expires in 8 hours

### Student Authentication
- Moodle credential verification
- Token exchange with Moodle LMS
- Encrypted token storage for submissions

## 📊 API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/staff/login` | Staff login |
| POST | `/auth/student/login` | Student login with Moodle credentials |
| POST | `/auth/student/logout` | Student logout |

### Upload (Staff Only)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/upload/single` | Upload single file |
| POST | `/upload/bulk` | Upload multiple files |
| POST | `/upload/validate` | Validate filename |

### Student
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/student/dashboard` | Get assigned papers |
| GET | `/student/paper/{id}/view` | View paper content |
| POST | `/student/submit/{id}` | Submit paper to Moodle |
| GET | `/student/submission/{id}/status` | Check submission status |

### Admin
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/admin/mappings` | List subject mappings |
| POST | `/admin/mappings` | Create mapping |
| GET | `/admin/queue` | View submission queue |
| GET | `/admin/stats` | System statistics |

## 🔧 Moodle Configuration

### Required Moodle Setup

1. **Enable Web Services**
   - Site administration → Advanced features → Enable web services

2. **Create External Service**
   - Site administration → Server → Web services → External services
   - Create service: "FileUpload"
   - Add functions:
     - `core_webservice_get_site_info`
     - `mod_assign_save_submission`
     - `mod_assign_submit_for_grading`

3. **Create Token**
   - Site administration → Server → Web services → Manage tokens
   - Create token for admin user with "FileUpload" service

4. **Enable Upload**
   - Ensure `webservice/upload.php` is accessible
   - Configure max upload size in Moodle settings

## 📦 Project Structure

```
exam_middleware/
├── app/
│   ├── api/
│   │   └── routes/
│   │       ├── admin.py      # Admin endpoints
│   │       ├── auth.py       # Authentication
│   │       ├── health.py     # Health check
│   │       ├── student.py    # Student endpoints
│   │       └── upload.py     # File upload
│   ├── core/
│   │   ├── config.py         # Configuration
│   │   └── security.py       # Security utilities
│   ├── db/
│   │   ├── database.py       # Database connection
│   │   └── models.py         # SQLAlchemy models
│   ├── schemas/
│   │   └── schemas.py        # Pydantic schemas
│   ├── services/
│   │   ├── artifact_service.py    # Artifact management
│   │   ├── file_processor.py      # File processing
│   │   ├── moodle_client.py       # Moodle API client
│   │   └── submission_service.py  # Submission workflow
│   ├── templates/
│   │   ├── staff_upload.html      # Staff portal
│   │   └── student_portal.html    # Student portal
│   └── main.py               # FastAPI application
├── uploads/                  # Temporary upload storage
├── storage/                  # Permanent file storage
├── .env                      # Environment configuration
├── .env.example              # Example configuration
├── init_db.py               # Database initialization
├── run.py                    # Application runner
└── requirements.txt          # Python dependencies
```

## 🧪 Testing

### Test with Sample Files

1. Create test files with correct naming:
   ```
   611221104088_19AI405.pdf
   611221104089_ML.pdf
   ```

2. Login to Staff Portal with `admin`/`admin123`

3. Upload the test files

4. Login to Student Portal with Moodle student credentials and register number

5. View and submit papers to Moodle

### API Testing with cURL

```bash
# Staff Login
curl -X POST http://localhost:8000/auth/staff/login \
  -F "username=admin" \
  -F "password=admin123"

# Upload File (use token from login)
curl -X POST http://localhost:8000/upload/single \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@611221104088_19AI405.pdf" \
  -F "exam_session=2024SPRING"

# Health Check
curl http://localhost:8000/health
```

## 📝 Workflow

1. **Staff uploads scanned papers** through the Staff Portal
2. **System extracts metadata** from filenames (register number, subject code)
3. **Papers are validated** and stored with unique transaction IDs
4. **Students login** with Moodle credentials and register number
5. **Students view** their assigned papers
6. **Students submit** papers directly to Moodle assignments
7. **System executes** 3-step Moodle submission:
   - Upload file to Moodle
   - Save submission draft
   - Submit for grading

## 🛡️ Security Considerations

- **Password Hashing**: bcrypt with 12 rounds
- **Token Encryption**: AES-256 (Fernet) for Moodle tokens
- **JWT Tokens**: Short-lived access tokens
- **File Validation**: Extension and size checks
- **Audit Logging**: All operations logged
- **CORS**: Configurable origin whitelist

## 🔄 Background Tasks (Optional)

For production deployment with Celery:

```bash
# Start Redis
redis-server

# Start Celery worker
celery -A app.tasks worker --loglevel=info
```

## 📈 Monitoring

- Health endpoint: `/health`
- Logs: `exam_middleware.log`
- Database audit table: `audit_logs`

## 🐛 Troubleshooting

### Database Connection Error
```
Ensure PostgreSQL is running and credentials in .env are correct
```

### Moodle Token Error
```
Verify MOODLE_ADMIN_TOKEN has required capabilities
Check Moodle external service configuration
```

### File Upload Failed
```
Check file size limits in Moodle
Verify assignment allows file submissions
```

## 📄 License

Not Licensed Yet.

## 🤝 Contributing

1. Fork the repository
2. Create feature branch
3. Commit changes
4. Push to branch
5. Create Pull Request
