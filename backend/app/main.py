
import os
import uuid
import json
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Literal

import jwt
from pwdlib import PasswordHash
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from fastapi import (
    FastAPI, Depends, HTTPException, Query, status, Request
)
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import (
    create_engine, String, Boolean, ForeignKey, Integer, Float,
    Date, DateTime, Text, UniqueConstraint, select, or_
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, Session, sessionmaker
)


# ============================================================
# 1. CONFIGURATION
# ============================================================

class Settings(BaseSettings):
    app_name: str = "ApexiveAI Workforce Payroll SaaS"
    environment: str = "development"
    database_url: str = "sqlite:///./dev.db"
    jwt_secret_key: str = "unsafe-development-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    cors_origins: str = "http://localhost:8081,http://127.0.0.1:8081"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )

    @property
    def allowed_origins(self):
        return [
            item.strip()
            for item in self.cors_origins.split(",")
            if item.strip()
        ]


settings = Settings()

if settings.environment.lower() == "production":
    if (
        len(settings.jwt_secret_key) < 32
        or settings.jwt_secret_key
        == "unsafe-development-secret-change-me"
    ):
        raise RuntimeError(
            "Set a strong JWT_SECRET_KEY before production."
        )


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("event", "request_id", "method", "path", "status_code", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=True)


handler = logging.StreamHandler()
handler.setFormatter(JsonLogFormatter())
request_logger = logging.getLogger("apexive.request")
request_logger.setLevel(logging.INFO)
request_logger.propagate = False
if not request_logger.handlers:
    request_logger.addHandler(handler)


# ============================================================
# 2. DATABASE — SQLite / PostgreSQL
# ============================================================

class Base(DeclarativeBase):
    pass


connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================
# 3. DATABASE MODELS
# ============================================================

class Company(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(200), index=True)
    code: Mapped[str] = mapped_column(
        String(50), unique=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    username: Mapped[str] = mapped_column(
        String(80), unique=True, index=True
    )
    email: Mapped[str] = mapped_column(
        String(254), unique=True, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(500))
    role: Mapped[str] = mapped_column(
        String(30), default="ADMIN", index=True
    )
    company_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("companies.id"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True
    )


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(
        String(500), default=""
    )
    latitude: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    longitude: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True
    )


class Worker(Base):
    __tablename__ = "workers"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "employee_code",
            name="uq_worker_company_employee_code"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id"), index=True
    )
    site_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("sites.id"), nullable=True, index=True
    )
    employee_code: Mapped[str] = mapped_column(
        String(80), index=True
    )
    full_name: Mapped[str] = mapped_column(String(200), index=True)
    phone: Mapped[str] = mapped_column(String(40), default="")
    monthly_salary_mmk: Mapped[int] = mapped_column(
        Integer, default=0
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True
    )


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "worker_id", "work_date", "shift",
            name="uq_attendance_company_worker_date_shift"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id"), index=True
    )
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("workers.id"), index=True
    )
    site_id: Mapped[str] = mapped_column(
        ForeignKey("sites.id"), index=True
    )
    work_date: Mapped[date] = mapped_column(Date, index=True)
    shift: Mapped[str] = mapped_column(String(20))
    attendance_status: Mapped[str] = mapped_column(
        String(20), default="PRESENT"
    )
    check_in_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    check_out_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    photo_url: Mapped[Optional[str]] = mapped_column(
        String(1000), nullable=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")


class Payroll(Base):
    __tablename__ = "payroll"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "worker_id", "year", "month",
            name="uq_payroll_company_worker_period"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id"), index=True
    )
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("workers.id"), index=True
    )
    year: Mapped[int] = mapped_column(Integer, index=True)
    month: Mapped[int] = mapped_column(Integer, index=True)
    base_salary_mmk: Mapped[int] = mapped_column(Integer, default=0)
    allowance_mmk: Mapped[int] = mapped_column(Integer, default=0)
    deduction_mmk: Mapped[int] = mapped_column(Integer, default=0)
    net_salary_mmk: Mapped[int] = mapped_column(Integer, default=0)
    payroll_status: Mapped[str] = mapped_column(
        String(20), default="DRAFT", index=True
    )


# ============================================================
# 4. PASSWORD HASHING + JWT
# ============================================================

password_hasher = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters.")
    return password_hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return password_hasher.verify(password, hashed)
    except Exception:
        return False


def create_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.id,
        "role": user.role,
        "company_id": user.company_id,
        "iat": now,
        "exp": now + timedelta(
            minutes=settings.access_token_expire_minutes
        ),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(401, "Bearer token required")

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Missing subject")
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(401, "Invalid or expired token")

    user = db.scalar(
        select(User).where(
            User.id == user_id,
            User.is_active.is_(True),
        )
    )

    if not user:
        raise HTTPException(401, "User not found or inactive")

    from app.subscriptions import enforce_company_subscription_status

    enforce_company_subscription_status(db, user, request.url.path)
    return user


def require_roles(*roles: str):
    def dependency(
        user: User = Depends(get_current_user),
    ) -> User:
        if user.role not in roles:
            raise HTTPException(403, "Insufficient permissions")
        return user
    return dependency


def require_company(user: User) -> str:
    if not user.company_id:
        raise HTTPException(
            403,
            "This operation requires a company account"
        )
    return user.company_id


# ============================================================
# 5. REQUEST / RESPONSE SCHEMAS
# ============================================================

class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class CompanyInput(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    code: str = Field(
        min_length=2,
        max_length=50,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    admin_username: str = Field(min_length=3, max_length=80)
    admin_email: EmailStr
    admin_password: str = Field(min_length=12, max_length=200)


class SiteInput(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    address: str = Field(default="", max_length=500)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


class WorkerInput(BaseModel):
    employee_code: str = Field(min_length=1, max_length=80)
    full_name: str = Field(min_length=2, max_length=200)
    phone: str = Field(default="", max_length=40)
    monthly_salary_mmk: int = Field(default=0, ge=0)
    site_id: Optional[str] = None


class AttendanceInput(BaseModel):
    worker_id: str
    site_id: str
    work_date: date
    shift: Literal["DAY", "NIGHT", "JOKER"]
    attendance_status: Literal[
        "PRESENT", "ABSENT", "LEAVE", "LATE"
    ] = "PRESENT"
    check_in_at: Optional[datetime] = None
    check_out_at: Optional[datetime] = None
    photo_url: Optional[str] = Field(default=None, max_length=1000)
    notes: str = Field(default="", max_length=2000)


class PayrollInput(BaseModel):
    worker_id: str
    year: int = Field(ge=2020, le=2100)
    month: int = Field(ge=1, le=12)
    base_salary_mmk: int = Field(ge=0)
    allowance_mmk: int = Field(default=0, ge=0)
    deduction_mmk: int = Field(default=0, ge=0)


# ============================================================
# 6. FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "ApexiveAI Workforce Payroll API: tenant-scoped companies, "
        "guard operations, attendance and controlled payroll periods. "
        "See backend/OPERATIONS.md for workflow and integration limits."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.on_event("startup")
def startup():
    if settings.environment.lower() != "production":
        Base.metadata.create_all(bind=engine)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", request_id):
        request_id = str(uuid.uuid4())
    started = time.perf_counter()
    try:
        response: Response = await call_next(request)
    except Exception:
        request_logger.exception(
            "request failed",
            extra={
                "event": "http.request.failed",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        raise
    response.headers["X-Request-ID"] = request_id
    request_logger.info(
        "request completed",
        extra={
            "event": "http.request.completed",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    )
    return response


@app.get("/", tags=["Health"])
def root():
    return {
        "service": settings.app_name,
        "status": "running",
        "docs": "/docs",
    }


@app.get("/api/v1/health", tags=["Health"])
def health():
    return {"status": "ok", "environment": settings.environment}


# ============================================================
# 7. AUTHENTICATION
# ============================================================

@app.post("/api/v1/auth/login", tags=["Authentication"])
def login(payload: LoginInput, db: Session = Depends(get_db)):
    user = db.scalar(
        select(User).where(User.username == payload.username)
    )

    if not user or not verify_password(
        payload.password, user.password_hash
    ):
        raise HTTPException(401, "Incorrect username or password")

    if not user.is_active:
        raise HTTPException(403, "Account is inactive")

    return {
        "access_token": create_token(user),
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "company_id": user.company_id,
            "is_active": user.is_active,
        },
    }


@app.get("/api/v1/auth/me", tags=["Authentication"])
def current_user_info(
    user: User = Depends(get_current_user),
):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "company_id": user.company_id,
        "is_active": user.is_active,
    }


# ============================================================
# 8. COMPANY / TENANT MANAGEMENT
# ============================================================

@app.post(
    "/api/v1/companies",
    status_code=201,
    tags=["Companies"],
)
def create_company(
    payload: CompanyInput,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("SUPERADMIN")),
):
    code = payload.code.upper()

    existing = db.scalar(
        select(Company).where(Company.code == code)
    )
    existing_user = db.scalar(
        select(User).where(
            or_(
                User.username == payload.admin_username,
                User.email == str(payload.admin_email),
            )
        )
    )

    if existing or existing_user:
        raise HTTPException(
            409,
            "Company code or admin username/email already exists",
        )

    company = Company(
        name=payload.name,
        code=code,
        is_active=True,
    )

    try:
        db.add(company)
        db.flush()

        admin = User(
            username=payload.admin_username,
            email=str(payload.admin_email),
            password_hash=hash_password(payload.admin_password),
            role="ADMIN",
            company_id=company.id,
            is_active=True,
        )
        db.add(admin)
        db.flush()
        audit(db, company.id, _, "company.created", "company", company.id)
        db.commit()
        db.refresh(company)

        return {
            "id": company.id,
            "name": company.name,
            "code": company.code,
            "admin_username": admin.username,
        }

    except Exception:
        db.rollback()
        raise


@app.get("/api/v1/companies", tags=["Companies"])
def list_companies(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("SUPERADMIN")),
):
    companies = db.scalars(
        select(Company).order_by(Company.name)
    ).all()

    return [
        {
            "id": c.id,
            "name": c.name,
            "code": c.code,
            "is_active": c.is_active,
        }
        for c in companies
    ]


# ============================================================
# 9. SITE MANAGEMENT
# ============================================================

@app.post("/api/v1/sites", status_code=201, tags=["Sites"])
def create_site(
    payload: SiteInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "MANAGER")),
):
    company_id = require_company(user)
    from app.subscriptions import assert_subscription_access

    assert_subscription_access(db, company_id, site_increment=1)

    site = Site(
        company_id=company_id,
        **payload.model_dump(),
    )
    db.add(site)
    db.flush()
    audit(db, company_id, user, "site.created", "site", site.id)
    db.commit()
    db.refresh(site)

    return {
        "id": site.id,
        "company_id": site.company_id,
        "name": site.name,
        "address": site.address,
        "latitude": site.latitude,
        "longitude": site.longitude,
        "is_active": site.is_active,
    }


@app.get("/api/v1/sites", tags=["Sites"])
def list_sites(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    rows = db.scalars(
        select(Site)
        .where(Site.company_id == company_id)
        .order_by(Site.name)
        .offset(offset)
        .limit(limit)
    ).all()

    return [
        {
            "id": s.id,
            "name": s.name,
            "address": s.address,
            "latitude": s.latitude,
            "longitude": s.longitude,
            "is_active": s.is_active,
        }
        for s in rows
    ]


@app.patch("/api/v1/sites/{site_id}/deactivate", tags=["Sites"])
def deactivate_site(
    site_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN")),
):
    company_id = require_company(user)
    site = db.scalar(
        select(Site).where(
            Site.id == site_id,
            Site.company_id == company_id,
        )
    )
    if not site:
        raise HTTPException(404, "Site not found")

    site.is_active = False
    audit(db, company_id, user, "site.deactivated", "site", site.id)
    db.commit()
    return {"status": "deactivated", "site_id": site.id}


# ============================================================
# 10. WORKER MANAGEMENT
# ============================================================

@app.post("/api/v1/workers", status_code=201, tags=["Workers"])
def create_worker(
    payload: WorkerInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "MANAGER")),
):
    company_id = require_company(user)
    from app.subscriptions import assert_subscription_access

    assert_subscription_access(db, company_id, employee_increment=1)

    duplicate = db.scalar(
        select(Worker).where(
            Worker.company_id == company_id,
            Worker.employee_code == payload.employee_code,
        )
    )
    if duplicate:
        raise HTTPException(409, "Employee code already exists")

    if payload.site_id:
        site = db.scalar(
            select(Site).where(
                Site.id == payload.site_id,
                Site.company_id == company_id,
                Site.is_active.is_(True),
            )
        )
        if not site:
            raise HTTPException(
                422,
                "Site does not belong to this company or is inactive",
            )

    worker = Worker(
        company_id=company_id,
        **payload.model_dump(),
    )
    db.add(worker)
    db.flush()
    if worker.site_id:
        initial_assignment = SiteAssignment(
            company_id=company_id,
            worker_id=worker.id,
            site_id=worker.site_id,
            effective_from=date.today(),
            created_by=user.id,
        )
        db.add(initial_assignment)
    audit(db, company_id, user, "employee.created", "employee", worker.id)
    db.commit()
    db.refresh(worker)

    return {
        "id": worker.id,
        "employee_code": worker.employee_code,
        "full_name": worker.full_name,
        "phone": worker.phone,
        "monthly_salary_mmk": worker.monthly_salary_mmk,
        "site_id": worker.site_id,
        "is_active": worker.is_active,
    }


@app.get("/api/v1/workers", tags=["Workers"])
def list_workers(
    search: Optional[str] = None,
    site_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    query = select(Worker).where(
        Worker.company_id == company_id
    )

    if search:
        term = f"%{search.strip()}%"
        query = query.where(
            or_(
                Worker.full_name.ilike(term),
                Worker.employee_code.ilike(term),
            )
        )

    if site_id:
        query = query.where(Worker.site_id == site_id)

    rows = db.scalars(
        query.order_by(Worker.full_name)
        .offset(offset)
        .limit(limit)
    ).all()

    return [
        {
            "id": w.id,
            "employee_code": w.employee_code,
            "full_name": w.full_name,
            "phone": w.phone,
            "monthly_salary_mmk": w.monthly_salary_mmk,
            "site_id": w.site_id,
            "is_active": w.is_active,
        }
        for w in rows
    ]


@app.get("/api/v1/workers/{worker_id}", tags=["Workers"])
def get_worker(
    worker_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    worker = db.scalar(
        select(Worker).where(
            Worker.id == worker_id,
            Worker.company_id == company_id,
        )
    )
    if not worker:
        raise HTTPException(404, "Worker not found")

    return {
        "id": worker.id,
        "employee_code": worker.employee_code,
        "full_name": worker.full_name,
        "phone": worker.phone,
        "monthly_salary_mmk": worker.monthly_salary_mmk,
        "site_id": worker.site_id,
        "is_active": worker.is_active,
    }


# ============================================================
# 11. ATTENDANCE MANAGEMENT
# ============================================================

@app.post(
    "/api/v1/attendance",
    status_code=201,
    tags=["Attendance"],
)
def create_attendance(
    payload: AttendanceInput,
    db: Session = Depends(get_db),
    user: User = Depends(
        require_roles("ADMIN", "MANAGER", "SUPERVISOR")
    ),
):
    company_id = require_company(user)
    from app.subscriptions import assert_subscription_access

    assert_subscription_access(db, company_id, feature="attendance")
    attendance_lock = db.scalar(
        select(AttendancePeriodLock).where(
            AttendancePeriodLock.company_id == company_id,
            AttendancePeriodLock.year == payload.work_date.year,
            AttendancePeriodLock.month == payload.work_date.month,
        )
    )
    if attendance_lock:
        raise HTTPException(
            409,
            "Attendance period is locked; submit an approved correction request.",
        )

    worker = db.scalar(
        select(Worker).where(
            Worker.id == payload.worker_id,
            Worker.company_id == company_id,
            Worker.is_active.is_(True),
        )
    )
    site = db.scalar(
        select(Site).where(
            Site.id == payload.site_id,
            Site.company_id == company_id,
            Site.is_active.is_(True),
        )
    )

    if not worker or not site:
        raise HTTPException(
            422,
            "Worker or site is invalid for this company",
        )

    if payload.check_in_at and payload.check_out_at:
        if payload.check_out_at < payload.check_in_at:
            raise HTTPException(
                422,
                "Check-out cannot be earlier than check-in",
            )

    duplicate = db.scalar(
        select(Attendance).where(
            Attendance.company_id == company_id,
            Attendance.worker_id == payload.worker_id,
            Attendance.work_date == payload.work_date,
            Attendance.shift == payload.shift,
        )
    )
    if duplicate:
        raise HTTPException(
            409,
            "Attendance already exists for worker/date/shift",
        )

    attendance = Attendance(
        company_id=company_id,
        **payload.model_dump(),
    )
    db.add(attendance)
    db.flush()
    audit(db, company_id, user, "attendance.created", "attendance", attendance.id)
    db.commit()
    db.refresh(attendance)

    return {
        "id": attendance.id,
        "worker_id": attendance.worker_id,
        "site_id": attendance.site_id,
        "work_date": attendance.work_date,
        "shift": attendance.shift,
        "attendance_status": attendance.attendance_status,
        "photo_url": attendance.photo_url,
    }


@app.get("/api/v1/attendance", tags=["Attendance"])
def list_attendance(
    work_date: Optional[date] = None,
    worker_id: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    query = select(Attendance).where(
        Attendance.company_id == company_id
    )

    if work_date:
        query = query.where(Attendance.work_date == work_date)
    if worker_id:
        query = query.where(Attendance.worker_id == worker_id)

    rows = db.scalars(
        query.order_by(Attendance.work_date.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    return [
        {
            "id": a.id,
            "worker_id": a.worker_id,
            "site_id": a.site_id,
            "work_date": a.work_date,
            "shift": a.shift,
            "attendance_status": a.attendance_status,
            "check_in_at": a.check_in_at,
            "check_out_at": a.check_out_at,
            "photo_url": a.photo_url,
            "notes": a.notes,
        }
        for a in rows
    ]


# ============================================================
# 12. PAYROLL MANAGEMENT
# ============================================================

@app.post("/api/v1/payroll", status_code=201, tags=["Payroll"])
def create_payroll(
    payload: PayrollInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PAYROLL")),
):
    raise HTTPException(
        410,
        "Manual payroll creation is disabled; use POST /api/v1/payroll/calculate "
        "to generate amounts from server-side records.",
    )


@app.get("/api/v1/payroll", tags=["Payroll"])
def list_payroll(
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
    month: Optional[int] = Query(default=None, ge=1, le=12),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    query = select(Payroll).where(
        Payroll.company_id == company_id
    )

    if year is not None:
        query = query.where(Payroll.year == year)
    if month is not None:
        query = query.where(Payroll.month == month)
    if user.role == "GUARD":
        employee_profile = db.scalar(
            select(EmployeeProfile).where(
                EmployeeProfile.user_id == user.id
            )
        )
        query = query.where(
            Payroll.worker_id == (
                employee_profile.worker_id if employee_profile else ""
            )
        )

    rows = db.scalars(
        query.order_by(Payroll.year.desc(), Payroll.month.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    return [
        {
            "id": p.id,
            "worker_id": p.worker_id,
            "year": p.year,
            "month": p.month,
            "base_salary_mmk": p.base_salary_mmk,
            "allowance_mmk": p.allowance_mmk,
            "deduction_mmk": p.deduction_mmk,
            "net_salary_mmk": p.net_salary_mmk,
            "payroll_status": p.payroll_status,
        }
        for p in rows
    ]


@app.post(
    "/api/v1/payroll/{payroll_id}/approve",
    tags=["Payroll"],
)
def approve_payroll(
    payroll_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN")),
):
    company_id = require_company(user)
    payroll = db.scalar(
        select(Payroll).where(
            Payroll.id == payroll_id,
            Payroll.company_id == company_id,
        )
    )
    if not payroll:
        raise HTTPException(404, "Payroll record not found")
    raise HTTPException(
        409,
        "Individual payroll approval is disabled; submit and approve the entire period.",
    )


from app.operations import (
    AttendancePeriodLock,
    EmployeeProfile,
    SiteAssignment,
    audit,
    router as operations_router,
)
from app.subscriptions import router as subscriptions_router

app.include_router(operations_router)
app.include_router(subscriptions_router)
