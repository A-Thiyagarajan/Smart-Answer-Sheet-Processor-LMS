# Quick Start Guide - Examination Middleware

## Overview
The Examination Middleware is a FastAPI application that bridges scanned examination papers with Moodle LMS for student submissions.

## Running Locally (Development)

### Prerequisites
- Python 3.10+
- pip (or conda)

### Option 1: Using SQLite + Mock LMS (Recommended for Local Development)

**Setup:**
```bash
cd exam_middleware
python run.py
```

The `.env` file is pre-configured with:
- **Database**: SQLite (no external server needed)
- **Mock LMS**: Enabled (for testing without Moodle)
- **Debug Mode**: Enabled
- **Auto-reload**: Enabled

**Access Points:**
- Staff Portal: http://localhost:8000/portal/staff
- Student Portal: http://localhost:8000/portal/student
- API Documentation: http://localhost:8000/docs
- Health Check: http://localhost:8000/health

---

## Running in Production (Docker)

### Option 2: Using Docker Compose (PostgreSQL + Redis)

**Setup:**
```bash
cd exam_middleware

# Copy and configure environment
cp .env.example .env
# Edit .env with your production settings:
# - MOODLE_BASE_URL (Moodle instance URL)
# - MOODLE_ADMIN_TOKEN (from Moodle admin panel)
# - POSTGRES_PASSWORD (strong password)

# Start all services
docker-compose up -d

# Initialize database
docker exec -it exam_middleware python init_db.py

# Setup subject mappings
docker exec -it exam_middleware python setup_subject_mapping.py
```

---

## Configuration

### Environment Variables

**Application:**
- `DEBUG`: Enable debug mode (default: False in production)
- `SECRET_KEY`: JWT secret key (MUST be set in production)
- `DATABASE_MODE`: Choose `sqlite` or `postgres`

**Database:**
- SQLite: Auto-created at `./exam_middleware.db`
- PostgreSQL: Configure `POSTGRES_*` variables

**Moodle Integration:**
- `MOODLE_BASE_URL`: Your Moodle instance URL
- `MOODLE_ADMIN_TOKEN`: Admin token from Moodle
- `MOCK_LMS_ENABLED`: Set to False in production

**File Storage:**
- `UPLOAD_DIR`: Directory for uploaded files (default: `./uploads`)
- `MAX_FILE_SIZE_MB`: Maximum upload size (default: 50MB)

---

## Project Structure

```
exam_middleware/
├── app/
│   ├── main.py              # FastAPI application entry point
│   ├── core/
│   │   ├── config.py        # Configuration management
│   │   └── security.py      # Authentication & security
│   ├── api/
│   │   └── routes/          # API endpoints
│   ├── db/
│   │   ├── database.py      # Database setup
│   │   └── models.py        # SQLAlchemy models
│   └── services/            # Business logic
├── run.py                   # Application launcher
├── init_db.py               # Database initialization
├── setup_subject_mapping.py # Subject configuration
├── .env                     # Environment configuration (generated)
├── docker-compose.yml       # Production Docker setup
└── docker-compose.dev.yml   # Development Docker setup
```

---

## API Workflow

### 1. Staff Upload Operations
```
POST /api/upload/file
- Authenticated with JWT
- Accepts scanned answer sheets
- Returns submission ID
```

### 2. File Processing
```
POST /api/upload/process/{submission_id}
- Processes uploaded files
- Validates exam data
- Extracts student information
```

### 3. Mock Moodle (Development Only)
```
GET /api/mock/courses
POST /api/mock/submit
- Simulates Moodle API responses
- Returns mock assignment IDs
```

### 4. Health Check
```
GET /health
- Returns application status
- Checks database connectivity
```

---

## Authentication

### Staff (Web Portal)
- Login endpoint: `POST /auth/staff/login`
- Returns JWT token valid for 60 minutes
- Use token in `Authorization: Bearer <token>` header

### Student (Web Portal)
- OAuth redirect to Moodle
- Session stored in SQLite/PostgreSQL

---

## Troubleshooting

### Port Already in Use
```bash
# Kill process on port 8000
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

### Database Connection Errors
- **SQLite**: Check file permissions in `./exam_middleware.db`
- **PostgreSQL**: Verify `docker-compose up` completed successfully

### Mock LMS Not Working
- Ensure `MOCK_LMS_ENABLED=True` in `.env`
- Check logs: `tail -f logs/app.log`

---

## Deployment Checklist

- [ ] Copy `.env.example` to `.env`
- [ ] Set strong `SECRET_KEY`
- [ ] Configure Moodle connection:
  - [ ] Get `MOODLE_BASE_URL` from admin
  - [ ] Generate `MOODLE_ADMIN_TOKEN`
- [ ] Set PostgreSQL password
- [ ] Run `docker-compose up -d`
- [ ] Run `python init_db.py`
- [ ] Configure subject mappings
- [ ] Test staff login: http://localhost:8000/portal/staff
- [ ] Test student portal: http://localhost:8000/portal/student
- [ ] Verify API docs: http://localhost:8000/docs

---

## For More Information

- See [DEPLOYMENT.md](DEPLOYMENT.md) for comprehensive deployment guide
- See [CLEANUP_REPORT.md](CLEANUP_REPORT.md) for project optimization details
- See [USAGE.md](USAGE.md) for detailed API usage examples

---

**Last Updated:** April 2026  
**Status:** Production Ready ✅
