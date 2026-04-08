# Examination Middleware

A FastAPI-based middleware system that bridges scanned examination answer sheets with Moodle LMS, enabling secure student submissions.

## 🌟 Features

- **Staff Upload Portal**: Bulk upload of scanned answer sheets with automatic metadata extraction
- **Student Portal**: View and submit assigned papers directly to Moodle
- **Moodle Integration**: Complete 3-step submission workflow (upload → save → submit)
- **Security**: JWT authentication for staff, Moodle token exchange for students
- **Audit Trail**: Complete logging of all operations
- **Filename Validation**: Automatic extraction of register number and subject code

## 📋 Prerequisites

- Python 3.10+
- PostgreSQL 14+
- Moodle LMS with Web Services enabled
- Redis (optional, for background tasks)

## 🚀 Quick Start

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

### 6. Initialize Database

```bash
python init_db.py
```

This will:
- Create all required tables
- Create default admin user (username: `admin`, password: `admin123`)
- Seed subject-to-assignment mappings
- Configure system settings

### 7. Setup Subject Mappings

For each subject/assignment, run the setup script to configure the correct Moodle assignment ID:

```bash
python setup_subject_mapping.py
```

This interactive script will:
- Connect to Moodle and find the assignment details
- Create or update the subject mapping in the database
- Fix any existing artifacts with incorrect assignment IDs

**Example Session:**
```
Enter subject code: 19AI411
Enter subject name: Natural Language Processing (optional)
Enter course module ID from URL: 7
Moodle username: admin
Moodle password: ****

✓ Found assignment and updated database
✓ Fixed 2 existing artifacts
```

**Note:** The course module ID is found in Moodle assignment URLs:
```
http://localhost/mod/assign/view.php?id=7
                                      ^^^ This is the course module ID
```

### 8. Run the Application

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
     - `mod_assign_get_assignments`
     - `core_course_get_courses`

3. **Create Token**
   - Site administration → Server → Web services → Manage tokens
   - Create token for admin user with "FileUpload" service

4. **Enable Upload**
   - Ensure `webservice/upload.php` is accessible
   - Configure max upload size in Moodle settings

### Finding Assignment IDs

Moodle assignment URLs contain the **course module ID (CMID)**, not the assignment instance ID:
```
http://localhost/mod/assign/view.php?id=7
                                      ^^^ Course Module ID (CMID)
```

To find the correct **assignment instance ID** for your database:
1. Use the `setup_subject_mapping.py` script (recommended)
2. Or query Moodle database directly:
   ```sql
   SELECT a.id AS assignment_id, a.name, cm.id AS cmid
   FROM mdl_assign a
   JOIN mdl_course_modules cm ON cm.instance = a.id
   WHERE cm.id = 7;  -- Replace 7 with your CMID
   ```

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
├── init_db.py                # Database initialization
├── setup_subject_mapping.py  # Subject mapping setup tool
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

## 🎯 Common Operations

### Adding a New Subject

1. Create the assignment in Moodle
2. Note the assignment URL (e.g., `http://localhost/mod/assign/view.php?id=7`)
3. Run the setup script:
   ```bash
   python setup_subject_mapping.py
   ```
4. Follow the prompts to configure the mapping

### Checking Upload Status

View recent uploads:
```bash
# In PostgreSQL
SELECT id, original_filename, parsed_subject_code, workflow_status, uploaded_at
FROM examination_artifacts
ORDER BY uploaded_at DESC
LIMIT 10;
```

### Viewing Student Sessions

See who's logged in:
```bash
# In PostgreSQL
SELECT moodle_username, register_number, moodle_fullname, created_at
FROM student_sessions
WHERE expires_at > NOW()
ORDER BY created_at DESC;
```

### Checking Subject Mappings

View all configured subjects:
```bash
# In PostgreSQL
SELECT subject_code, subject_name, moodle_course_id, moodle_assignment_id, is_active
FROM subject_mappings
WHERE is_active = true;
```

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

### Submission Failed: "Assignment X not found"

This error occurs when the assignment ID in the database doesn't match the actual Moodle assignment instance ID.

**Solution:**
1. Run the subject mapping setup script:
   ```bash
   python setup_subject_mapping.py
   ```
2. Enter the subject code and course module ID from the Moodle URL
3. The script will automatically find and update the correct assignment ID

**Important:** Moodle URLs show the course module ID (CMID), but the API needs the assignment instance ID. The setup script handles this conversion automatically.

### Papers Not Appearing in Student Dashboard

**Check:**
1. File naming follows correct pattern: `REGISTER_SUBJECT.pdf`
2. Student logged in with matching register number
3. Subject mapping exists in database
4. Paper status is "PENDING" (not "COMPLETED" or "FAILED")

**Fix:**
```bash
# Check artifact status
python -c "
from app.db.database import async_session_maker
from app.db.models import ExaminationArtifact
import asyncio

async def check():
    async with async_session_maker() as db:
        from sqlalchemy import select
        result = await db.execute(select(ExaminationArtifact))
        for a in result.scalars():
            print(f'{a.id}: {a.original_filename} - {a.workflow_status}')
asyncio.run(check())
"
```

## 📄 License

MIT License

## 🤝 Contributing

1. Fork the repository
2. Create feature branch
3. Commit changes
4. Push to branch
5. Create Pull Request
