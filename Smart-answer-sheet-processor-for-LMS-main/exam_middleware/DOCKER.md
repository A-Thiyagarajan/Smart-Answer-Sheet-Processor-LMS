# Docker Deployment Guide

## Quick Start

### Development Environment

1. **Copy environment file:**
   ```bash
   cp .env.docker .env
   ```

2. **Update environment variables in `.env`** (especially `SECRET_KEY`)

3. **Build and start services:**
   ```bash
   docker-compose up -d
   ```

4. **Run database migrations:**
   ```bash
   docker-compose exec app python init_db.py
   docker-compose exec app alembic upgrade head
   ```

5. **Access the application:**
   - Staff Portal: http://localhost:8000/portal/staff
   - Student Portal: http://localhost:8000/portal/student
   - API Docs: http://localhost:8000/docs
   - Flower (Celery Monitor): http://localhost:5555

### Production Environment

1. **Use production Dockerfile:**
   ```bash
   docker-compose -f docker-compose.prod.yml up -d
   ```

2. **Or build manually:**
   ```bash
   docker build -f Dockerfile.prod -t exam-middleware:latest .
   ```

## Docker Commands

### View logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f app
docker-compose logs -f celery_worker
```

### Stop services
```bash
docker-compose down
```

### Stop and remove volumes
```bash
docker-compose down -v
```

### Rebuild containers
```bash
docker-compose up -d --build
```

### Execute commands in container
```bash
# Run database migrations
docker-compose exec app alembic upgrade head

# Create superuser
docker-compose exec app python setup_subject_mapping.py

# Access Python shell
docker-compose exec app python
```

### Scale celery workers
```bash
docker-compose up -d --scale celery_worker=3
```

## Services

- **app**: Main FastAPI application (Port 8000)
- **postgres**: PostgreSQL database (Port 5432)
- **redis**: Redis cache/queue (Port 6379)
- **celery_worker**: Background task worker
- **flower**: Celery monitoring dashboard (Port 5555)

## Environment Variables

See `.env.docker` for all available configuration options.

## Data Persistence

Data is persisted in Docker volumes:
- `postgres_data`: Database files
- `redis_data`: Redis persistence
- `./uploads`: File uploads (mounted directory)
- `./storage`: Application storage (mounted directory)

## Troubleshooting

### Database connection issues
```bash
docker-compose exec postgres psql -U exam_user -d exam_middleware
```

### Redis connection issues
```bash
docker-compose exec redis redis-cli ping
```

### Check container health
```bash
docker-compose ps
```

### Reset everything
```bash
docker-compose down -v
docker-compose up -d --build
```
