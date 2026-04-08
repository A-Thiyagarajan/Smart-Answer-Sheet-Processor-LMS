# Quick Usage Guide - Examination Middleware

## Daily Operations

### 📤 Staff: Upload Papers

1. Start the server: `python run.py`
2. Open: http://localhost:8000/portal/staff
3. Login: `admin` / `admin123`
4. Upload scanned papers (filename format: `REGISTER_SUBJECT.pdf`)
5. Papers are automatically processed and assigned to students

### 👨‍🎓 Student: Submit Papers

1. Open: http://localhost:8000/portal/student
2. Login with:
   - Moodle username
   - Moodle password
   - Register number (12 digits)
3. View assigned papers
4. Click "Submit to Moodle" for each paper
5. Papers are uploaded directly to Moodle assignments

## Setup New Subject

When you need to add a new subject/assignment:

```bash
python setup_subject_mapping.py
```

**You'll need:**
- Subject code (e.g., `19AI411`)
- Assignment URL from Moodle (to extract course module ID)
- Moodle admin credentials

**The script will:**
- ✓ Find the correct assignment ID from Moodle
- ✓ Create/update database mapping
- ✓ Fix any existing papers with wrong IDs

## File Naming Rules

**Correct:**
- `212222240047_19AI405.pdf`
- `212221230038_ML.jpg`
- `611221104088_19AI411.png`

**Wrong:**
- `19AI405_212222240047.pdf` ❌ (reversed)
- `212222240047-19AI405.pdf` ❌ (wrong separator)
- `212222240047.pdf` ❌ (missing subject)
- `19AI405.pdf` ❌ (missing register)

**Format:** `{12-digit-register}_{SUBJECT-CODE}.{pdf|jpg|png}`

## Troubleshooting

### "Assignment X not found" error
→ Run `python setup_subject_mapping.py` to fix assignment ID mapping

### Student can't see uploaded paper
→ Check:
  - Filename follows correct format
  - Student logged in with matching register number
  - Subject mapping exists

### Paper stuck in "FAILED" status
→ Check logs in `exam_middleware.log` for error details

## Quick Commands

### Start Application
```bash
python run.py
```

### Setup New Subject
```bash
python setup_subject_mapping.py
```

### Initialize/Reset Database
```bash
python init_db.py
```

### View Logs
```bash
# Windows
type exam_middleware.log | Select-Object -Last 50

# Linux/Mac
tail -f exam_middleware.log
```

## Database Queries

### View Recent Uploads
```sql
SELECT id, original_filename, parsed_subject_code, workflow_status
FROM examination_artifacts
ORDER BY uploaded_at DESC LIMIT 10;
```

### View Subject Mappings
```sql
SELECT subject_code, moodle_assignment_id, subject_name
FROM subject_mappings
WHERE is_active = true;
```

### View Active Sessions
```sql
SELECT moodle_username, register_number, created_at
FROM student_sessions
WHERE expires_at > NOW();
```

## URLs

- **Staff Portal:** http://localhost:8000/portal/staff
- **Student Portal:** http://localhost:8000/portal/student
- **API Docs:** http://localhost:8000/docs
- **Health Check:** http://localhost:8000/health

## Support

Check the detailed README.md for:
- Complete installation instructions
- API documentation
- Advanced configuration
- Security settings
