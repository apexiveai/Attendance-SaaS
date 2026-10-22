import calendar
import csv
import hashlib
import io
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.main import (
    Attendance,
    Base,
    Company,
    Payroll,
    Site,
    User,
    Worker,
    get_current_user,
    get_db,
    hash_password,
    require_company,
    require_roles,
)


router = APIRouter(prefix="/api/v1", tags=["Workforce Operations"])


def new_id() -> str:
    return str(uuid.uuid4())


class EmployeeProfile(Base):
    __tablename__ = "employee_profiles"
    __table_args__ = (UniqueConstraint("user_id"),)

    worker_id: Mapped[str] = mapped_column(
        ForeignKey("workers.id"), primary_key=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    address: Mapped[str] = mapped_column(String(500), default="")
    emergency_contact_name: Mapped[str] = mapped_column(String(200), default="")
    emergency_contact_phone: Mapped[str] = mapped_column(String(40), default="")
    identity_reference: Mapped[str] = mapped_column(String(100), default="")
    contract_type: Mapped[str] = mapped_column(String(40), default="PERMANENT")
    employment_status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    join_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    final_working_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    probation_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    position: Mapped[str] = mapped_column(String(120), default="Security Guard")
    department: Mapped[str] = mapped_column(String(120), default="")
    supervisor_name: Mapped[str] = mapped_column(String(200), default="")
    photo_url: Mapped[str] = mapped_column(String(1000), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class EmployeeRecord(Base):
    __tablename__ = "employee_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"), index=True)
    category: Mapped[str] = mapped_column(String(30), index=True)
    title: Mapped[str] = mapped_column(String(160))
    reference_number: Mapped[str] = mapped_column(String(100), default="")
    issued_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expires_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    evidence_url: Mapped[str] = mapped_column(String(1000), default="")
    note: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class SiteAssignment(Base):
    __tablename__ = "site_assignments"
    __table_args__ = (UniqueConstraint("worker_id", "site_id", "effective_from"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"), index=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True)
    effective_from: Mapped[date] = mapped_column(Date, index=True)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class SalaryHistory(Base):
    __tablename__ = "salary_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"), index=True)
    wage_basis: Mapped[str] = mapped_column(String(20), default="MONTHLY")
    base_rate_mmk: Mapped[int] = mapped_column(Integer)
    fixed_allowance_mmk: Mapped[int] = mapped_column(Integer, default=0)
    salary_grade: Mapped[str] = mapped_column(String(80), default="")
    effective_from: Mapped[date] = mapped_column(Date, index=True)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    approved_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str] = mapped_column(String(500), default="")


class WorkShift(Base):
    __tablename__ = "work_shifts"
    __table_args__ = (UniqueConstraint("company_id", "name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    start_time: Mapped[str] = mapped_column(String(5))
    end_time: Mapped[str] = mapped_column(String(5))
    scheduled_hours: Mapped[float] = mapped_column(Float, default=8)
    night_allowance_mmk: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(default=True)


class RosterAssignment(Base):
    __tablename__ = "roster_assignments"
    __table_args__ = (UniqueConstraint("company_id", "worker_id", "shift_date", "shift_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"), index=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True)
    shift_id: Mapped[str] = mapped_column(ForeignKey("work_shifts.id"))
    shift_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="SCHEDULED")
    replacement_worker_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("workers.id"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"), index=True)
    leave_type: Mapped[str] = mapped_column(String(40))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    reviewed_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class LeaveEntitlement(Base):
    __tablename__ = "leave_entitlements"
    __table_args__ = (UniqueConstraint("company_id", "worker_id", "leave_type", "year"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"), index=True)
    leave_type: Mapped[str] = mapped_column(String(40))
    year: Mapped[int] = mapped_column(Integer)
    entitlement_days: Mapped[float] = mapped_column(Float, default=0)
    carryover_days: Mapped[float] = mapped_column(Float, default=0)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class PayrollComponent(Base):
    __tablename__ = "payroll_components"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    payroll_id: Mapped[str] = mapped_column(ForeignKey("payroll.id"), index=True)
    component_type: Mapped[str] = mapped_column(String(20))
    code: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(String(200))
    amount_mmk: Mapped[int] = mapped_column(Integer)
    source_reference: Mapped[str] = mapped_column(String(100), default="")


class PayrollPayment(Base):
    __tablename__ = "payroll_payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    payroll_id: Mapped[str] = mapped_column(ForeignKey("payroll.id"), index=True)
    amount_mmk: Mapped[int] = mapped_column(Integer)
    payment_date: Mapped[date] = mapped_column(Date)
    payment_method: Mapped[str] = mapped_column(String(40), default="CASH")
    reference: Mapped[str] = mapped_column(String(120), default="")
    payment_status: Mapped[str] = mapped_column(String(20), default="CONFIRMED")
    recorded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class PayrollPeriod(Base):
    __tablename__ = "payroll_periods"
    __table_args__ = (UniqueConstraint("company_id", "year", "month"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    input_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    calculated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    submitted_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    approved_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approval_reason: Mapped[str] = mapped_column(String(500), default="")
    locked_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    locked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AttendancePeriodLock(Base):
    __tablename__ = "attendance_period_locks"
    __table_args__ = (UniqueConstraint("company_id", "year", "month"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    locked_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    reason: Mapped[str] = mapped_column(String(500))


class PayrollRunRequest(Base):
    __tablename__ = "payroll_run_requests"
    __table_args__ = (UniqueConstraint("company_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    response_json: Mapped[str] = mapped_column(Text)


class PayrollPermissionGrant(Base):
    __tablename__ = "payroll_permission_grants"
    __table_args__ = (UniqueConstraint("company_id", "user_id", "permission"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    permission: Mapped[str] = mapped_column(String(50))
    granted_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class PayrollAdjustment(Base):
    __tablename__ = "payroll_adjustments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    payroll_id: Mapped[str] = mapped_column(ForeignKey("payroll.id"), index=True)
    effective_year: Mapped[int] = mapped_column(Integer)
    effective_month: Mapped[int] = mapped_column(Integer)
    amount_mmk: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )


class ComplianceRule(Base):
    __tablename__ = "compliance_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    code: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(120))
    effective_from: Mapped[date] = mapped_column(Date, index=True)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    configuration_json: Mapped[str] = mapped_column(Text)
    reference_note: Mapped[str] = mapped_column(String(500), default="")
    reviewed_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class LoanAdvance(Base):
    __tablename__ = "loans_advances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    principal_mmk: Mapped[int] = mapped_column(Integer)
    outstanding_mmk: Mapped[int] = mapped_column(Integer)
    monthly_repayment_mmk: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    approved_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ShiftSwapRequest(Base):
    __tablename__ = "shift_swap_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    roster_assignment_id: Mapped[str] = mapped_column(
        ForeignKey("roster_assignments.id"), index=True
    )
    requesting_worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"))
    replacement_worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    reviewed_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )


class ExpenseClaim(Base):
    __tablename__ = "expense_claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"), index=True)
    claim_date: Mapped[date] = mapped_column(Date)
    category: Mapped[str] = mapped_column(String(80))
    amount_mmk: Mapped[int] = mapped_column(Integer)
    evidence_url: Mapped[str] = mapped_column(String(1000), default="")
    note: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )


class SiteContract(Base):
    __tablename__ = "site_contracts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), index=True)
    customer_name: Mapped[str] = mapped_column(String(200))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    required_guards: Mapped[int] = mapped_column(Integer, default=0)
    billing_rate_mmk: Mapped[int] = mapped_column(Integer, default=0)
    guard_rate_basis: Mapped[str] = mapped_column(String(20), default="MONTHLY")
    is_active: Mapped[bool] = mapped_column(default=True)


class CompanyPolicy(Base):
    __tablename__ = "company_policies"
    __table_args__ = (UniqueConstraint("company_id", "key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    key: Mapped[str] = mapped_column(String(80))
    value: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class AttendanceEvidence(Base):
    __tablename__ = "attendance_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    attendance_id: Mapped[str] = mapped_column(ForeignKey("attendance.id"), index=True)
    photo_url: Mapped[str] = mapped_column(String(1000))
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gps_consent: Mapped[bool] = mapped_column(default=False)
    ocr_text: Mapped[str] = mapped_column(Text, default="")
    review_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    reviewed_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class AttendanceCorrection(Base):
    __tablename__ = "attendance_corrections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    attendance_id: Mapped[str] = mapped_column(ForeignKey("attendance.id"), index=True)
    changes_json: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reviewed_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ApprovedOvertime(Base):
    __tablename__ = "approved_overtime"
    __table_args__ = (UniqueConstraint("attendance_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    attendance_id: Mapped[str] = mapped_column(ForeignKey("attendance.id"), index=True)
    approved_hours: Mapped[float] = mapped_column(Float)
    approved_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class AuditRecord(Base):
    __tablename__ = "audit_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class InputModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class EmployeeProfileInput(InputModel):
    date_of_birth: Optional[date] = None
    address: str = Field(default="", max_length=500)
    emergency_contact_name: str = Field(default="", max_length=200)
    emergency_contact_phone: str = Field(default="", max_length=40)
    identity_reference: str = Field(default="", max_length=100)
    contract_type: Literal["PERMANENT", "FIXED_TERM", "CASUAL", "PART_TIME"] = "PERMANENT"
    employment_status: Literal["ACTIVE", "PROBATION", "ON_LEAVE", "RESIGNED", "TERMINATED"] = "ACTIVE"
    join_date: Optional[date] = None
    final_working_date: Optional[date] = None
    probation_end_date: Optional[date] = None
    position: str = Field(default="Security Guard", max_length=120)
    department: str = Field(default="", max_length=120)
    supervisor_name: str = Field(default="", max_length=200)
    photo_url: str = Field(default="", max_length=1000)


class EmployeeRecordInput(InputModel):
    category: Literal["IDENTITY", "CONTRACT", "CERTIFICATE", "TRAINING", "DISCIPLINARY", "EXIT_CHECKLIST", "OTHER"]
    title: str = Field(min_length=2, max_length=160)
    reference_number: str = Field(default="", max_length=100)
    issued_on: Optional[date] = None
    expires_on: Optional[date] = None
    evidence_url: str = Field(default="", max_length=1000)
    note: str = Field(default="", max_length=500)


class AccountLinkInput(InputModel):
    user_id: str


class GuardAccountInput(InputModel):
    username: str = Field(min_length=3, max_length=80)
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)


class AssignmentInput(InputModel):
    site_id: str
    effective_from: date


class SalaryInput(InputModel):
    wage_basis: Literal["MONTHLY", "DAILY", "HOURLY", "SHIFT"] = "MONTHLY"
    base_rate_mmk: int = Field(ge=0)
    fixed_allowance_mmk: int = Field(default=0, ge=0)
    salary_grade: str = Field(default="", max_length=80)
    effective_from: date
    note: str = Field(default="", max_length=500)


class ShiftInput(InputModel):
    name: str = Field(min_length=2, max_length=80)
    start_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    scheduled_hours: float = Field(default=8, gt=0, le=24)
    night_allowance_mmk: int = Field(default=0, ge=0)


class RosterInput(InputModel):
    worker_id: str
    site_id: str
    shift_id: str
    shift_date: date


class LeaveInput(InputModel):
    worker_id: str
    leave_type: Literal["ANNUAL", "CASUAL", "MEDICAL", "UNPAID", "MATERNITY", "PATERNITY", "OTHER"]
    start_date: date
    end_date: date
    reason: str = Field(default="", max_length=1000)


class LeaveEntitlementInput(InputModel):
    entitlement_days: float = Field(ge=0, le=366)
    carryover_days: float = Field(default=0, ge=0, le=366)


class EvidenceInput(InputModel):
    photo_url: str = Field(min_length=1, max_length=1000)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    gps_consent: bool = False
    ocr_text: str = Field(default="", max_length=4000)


class OvertimeInput(InputModel):
    approved_hours: float = Field(ge=0, le=24)


class AttendanceCorrectionInput(InputModel):
    attendance_status: Optional[Literal["PRESENT", "ABSENT", "LEAVE", "LATE"]] = None
    check_in_at: Optional[datetime] = None
    check_out_at: Optional[datetime] = None
    site_id: Optional[str] = None
    reason: str = Field(min_length=3, max_length=500)


class ReviewInput(InputModel):
    status: Literal["APPROVED", "REJECTED"]
    note: str = Field(default="", max_length=500)


class LoanInput(InputModel):
    worker_id: str
    kind: Literal["LOAN", "ADVANCE"]
    principal_mmk: int = Field(gt=0)
    monthly_repayment_mmk: int = Field(gt=0)


class ClaimInput(InputModel):
    worker_id: str
    claim_date: date
    category: str = Field(min_length=2, max_length=80)
    amount_mmk: int = Field(gt=0)
    evidence_url: str = Field(default="", max_length=1000)
    note: str = Field(default="", max_length=500)


class ContractInput(InputModel):
    site_id: str
    customer_name: str = Field(min_length=2, max_length=200)
    start_date: date
    end_date: Optional[date] = None
    required_guards: int = Field(default=0, ge=0)
    billing_rate_mmk: int = Field(default=0, ge=0)
    guard_rate_basis: Literal["MONTHLY", "DAILY", "SHIFT"] = "MONTHLY"


class PolicyInput(InputModel):
    key: Literal[
        "working_days_per_month", "hours_per_day", "overtime_multiplier",
        "late_deduction_per_minute", "photo_attendance_enabled",
        "ocr_enabled", "gps_attendance_enabled", "deduction_cap_mmk",
        "night_shift_allowance_mmk",
    ]
    value: str = Field(min_length=1, max_length=200)


class PaymentInput(InputModel):
    amount_mmk: int = Field(gt=0)
    payment_date: date
    payment_method: Literal["CASH", "BANK_TRANSFER", "MOBILE_WALLET", "OTHER"] = "CASH"
    reference: str = Field(default="", max_length=120)


class PeriodReasonInput(InputModel):
    reason: str = Field(min_length=3, max_length=500)


class PayrollAdjustmentInput(InputModel):
    amount_mmk: int = Field(ne=0)
    reason: str = Field(min_length=3, max_length=500)


class ComplianceRuleInput(InputModel):
    code: Literal["PIT", "SSB", "MINIMUM_WAGE", "OVERTIME", "STATUTORY_REPORT"]
    name: str = Field(min_length=2, max_length=120)
    effective_from: date
    effective_to: Optional[date] = None
    configuration: dict = Field(default_factory=dict)
    reference_note: str = Field(min_length=3, max_length=500)


class PaymentAttemptInput(PaymentInput):
    payment_status: Literal["PENDING", "FAILED"]


def audit(
    db: Session, company_id: str, actor: User, action: str,
    entity_type: str, entity_id: Optional[str], details: dict | None = None,
) -> None:
    pending = list(db.new)
    db.flush()
    if entity_id is None:
        tables = {
            "employee_record": "employee_records",
            "site_assignment": "site_assignments",
            "salary_history": "salary_history",
            "shift": "work_shifts",
            "roster_assignment": "roster_assignments",
            "shift_swap_request": "shift_swap_requests",
            "leave_request": "leave_requests",
            "leave_entitlement": "leave_entitlements",
            "attendance_evidence": "attendance_evidence",
            "attendance_correction": "attendance_corrections",
            "loan_advance": "loans_advances",
            "expense_claim": "expense_claims",
            "site_contract": "site_contracts",
            "company_policy": "company_policies",
            "payroll_adjustment": "payroll_adjustments",
            "compliance_rule": "compliance_rules",
            "payroll_payment": "payroll_payments",
        }
        expected_table = tables.get(entity_type)
        pending_entity = next(
            (
                item for item in reversed(pending)
                if expected_table and getattr(type(item), "__tablename__", None) == expected_table
            ),
            None,
        )
        entity_id = getattr(pending_entity, "id", None)
    if entity_id is None:
        raise ValueError(f"Cannot write audit record without an entity id: {entity_type}")
    db.add(AuditRecord(
        company_id=company_id,
        actor_id=actor.id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details_json=json.dumps(details or {}, default=str),
    ))


def get_worker(db: Session, company_id: str, worker_id: str) -> Worker:
    worker = db.scalar(select(Worker).where(
        Worker.id == worker_id, Worker.company_id == company_id
    ))
    if not worker:
        raise HTTPException(404, "Employee not found")
    return worker


def get_site(db: Session, company_id: str, site_id: str) -> Site:
    site = db.scalar(select(Site).where(
        Site.id == site_id, Site.company_id == company_id
    ))
    if not site:
        raise HTTPException(404, "Site not found")
    return site


def payroll_workers(
    db: Session, company_id: str, start: date, end: date
) -> list[Worker]:
    workers = db.scalars(select(Worker).where(
        Worker.company_id == company_id
    ).order_by(Worker.id)).all()
    eligible = []
    for worker in workers:
        profile = db.get(EmployeeProfile, worker.id)
        terminal = bool(
            profile
            and profile.employment_status in ("RESIGNED", "TERMINATED")
        )
        if terminal:
            if not profile.final_working_date or profile.final_working_date < start:
                continue
            if profile.join_date and profile.join_date > end:
                continue
            eligible.append(worker)
        elif worker.is_active:
            eligible.append(worker)
    return eligible


def require_worker_access(
    db: Session, company_id: str, user: User, worker_id: str
) -> None:
    if user.role != "GUARD":
        return
    profile = db.scalar(select(EmployeeProfile).join(
        Worker, Worker.id == EmployeeProfile.worker_id
    ).where(
        EmployeeProfile.user_id == user.id,
        EmployeeProfile.worker_id == worker_id,
        Worker.company_id == company_id,
    ))
    if not profile:
        raise HTTPException(403, "You can only access your own employee records")


def policy_value(db: Session, company_id: str, key: str, default: str) -> str:
    policy = db.scalar(select(CompanyPolicy).where(
        CompanyPolicy.company_id == company_id, CompanyPolicy.key == key
    ))
    return policy.value if policy else default


def calculate_payroll_amounts(
    *, wage_basis: str, rate: int, fixed_allowance: int, worked_days: int,
    scheduled_days: int, worked_hours: float, overtime_hours: float,
    night_shifts: int, night_allowance: int, overtime_multiplier: float,
    loan_repayment: int, unpaid_leave_days: int,
    active_calendar_days: Optional[int] = None, period_calendar_days: int = 30,
    base_override: Optional[int] = None,
    allowance_override: Optional[int] = None,
    overtime_pay_override: Optional[int] = None,
    unpaid_leave_deduction_override: Optional[int] = None,
) -> list[dict]:
    days = max(scheduled_days, 1)
    if wage_basis == "MONTHLY":
        employed_days = min(active_calendar_days, period_calendar_days) if active_calendar_days is not None else period_calendar_days
        base = base_override if base_override is not None else round(rate * employed_days / max(period_calendar_days, 1))
        hourly_rate = rate / (days * 8)
    elif wage_basis == "DAILY":
        base = rate * worked_days
        hourly_rate = rate / 8
    elif wage_basis == "SHIFT":
        base = rate * worked_days
        hourly_rate = rate / 8
    elif wage_basis == "HOURLY":
        base = round(rate * worked_hours)
        hourly_rate = rate
    else:
        raise HTTPException(422, "Unsupported wage basis")
    overtime = (
        overtime_pay_override
        if overtime_pay_override is not None
        else round(max(0, overtime_hours) * hourly_rate * overtime_multiplier)
    )
    items = [
        {"type": "EARNING", "code": "BASE", "description": "Base wages", "amount_mmk": base},
    ]
    allowance_amount = allowance_override if allowance_override is not None else fixed_allowance
    if allowance_amount:
        items.append({"type": "EARNING", "code": "FIXED_ALLOWANCE", "description": "Fixed allowance", "amount_mmk": allowance_amount})
    if overtime:
        items.append({"type": "EARNING", "code": "OVERTIME", "description": "Approved overtime", "amount_mmk": overtime})
    if night_shifts and night_allowance:
        items.append({"type": "EARNING", "code": "NIGHT_ALLOWANCE", "description": "Night shift allowance", "amount_mmk": night_shifts * night_allowance})
    if loan_repayment:
        items.append({"type": "DEDUCTION", "code": "LOAN_REPAYMENT", "description": "Approved loan / advance repayment", "amount_mmk": loan_repayment})
    if unpaid_leave_days:
        unpaid = (
            unpaid_leave_deduction_override
            if unpaid_leave_deduction_override is not None
            else round(rate / days * unpaid_leave_days) if wage_basis == "MONTHLY" else 0
        )
        if unpaid:
            items.append({"type": "DEDUCTION", "code": "UNPAID_LEAVE", "description": "Unpaid leave", "amount_mmk": unpaid})
    if sum(item["amount_mmk"] for item in items if item["type"] == "DEDUCTION") > sum(item["amount_mmk"] for item in items if item["type"] == "EARNING"):
        raise HTTPException(422, "Deductions exceed earnings; review payroll inputs")
    return items


def payroll_totals(items: list[dict]) -> tuple[int, int, int]:
    gross = sum(i["amount_mmk"] for i in items if i["type"] == "EARNING")
    deductions = sum(i["amount_mmk"] for i in items if i["type"] == "DEDUCTION")
    return gross, deductions, gross - deductions


def payroll_fingerprint(
    db: Session, company_id: str, start: date, end: date
) -> str:
    workers = payroll_workers(db, company_id, start, end)
    worker_ids = [worker.id for worker in workers]
    salary_rows = db.scalars(select(SalaryHistory).where(
        SalaryHistory.company_id == company_id,
        SalaryHistory.worker_id.in_(worker_ids or [""]),
        SalaryHistory.effective_from <= end,
    ).order_by(SalaryHistory.worker_id, SalaryHistory.effective_from)).all()
    attendance_rows = db.scalars(select(Attendance).where(
        Attendance.company_id == company_id,
        Attendance.worker_id.in_(worker_ids or [""]),
        Attendance.work_date.between(start, end),
    ).order_by(Attendance.worker_id, Attendance.work_date, Attendance.shift)).all()
    attendance_ids = [row.id for row in attendance_rows]
    overtime_rows = db.scalars(select(ApprovedOvertime).where(
        ApprovedOvertime.company_id == company_id,
        ApprovedOvertime.attendance_id.in_(attendance_ids or [""]),
    ).order_by(ApprovedOvertime.attendance_id)).all()
    leaves = db.scalars(select(LeaveRequest).where(
        LeaveRequest.company_id == company_id,
        LeaveRequest.worker_id.in_(worker_ids or [""]),
        LeaveRequest.status == "APPROVED",
        LeaveRequest.start_date <= end,
        LeaveRequest.end_date >= start,
    ).order_by(LeaveRequest.worker_id, LeaveRequest.start_date)).all()
    loans = db.scalars(select(LoanAdvance).where(
        LoanAdvance.company_id == company_id,
        LoanAdvance.worker_id.in_(worker_ids or [""]),
        LoanAdvance.status == "APPROVED",
    ).order_by(LoanAdvance.worker_id, LoanAdvance.id)).all()
    claims = db.scalars(select(ExpenseClaim).where(
        ExpenseClaim.company_id == company_id,
        ExpenseClaim.worker_id.in_(worker_ids or [""]),
        ExpenseClaim.status == "APPROVED",
        ExpenseClaim.claim_date.between(start, end),
    ).order_by(ExpenseClaim.worker_id, ExpenseClaim.claim_date)).all()
    adjustments = db.scalars(select(PayrollAdjustment).where(
        PayrollAdjustment.company_id == company_id,
        PayrollAdjustment.effective_year == start.year,
        PayrollAdjustment.effective_month == start.month,
        PayrollAdjustment.status == "APPROVED",
    ).order_by(PayrollAdjustment.id)).all()
    policies = db.scalars(select(CompanyPolicy).where(
        CompanyPolicy.company_id == company_id
    ).order_by(CompanyPolicy.key)).all()
    data = {
        "workers": [(w.id, w.monthly_salary_mmk, w.is_active) for w in workers],
        "salary": [(s.worker_id, s.wage_basis, s.base_rate_mmk, s.fixed_allowance_mmk, s.effective_from, s.effective_to) for s in salary_rows],
        "attendance": [(a.id, a.worker_id, a.work_date, a.shift, a.attendance_status, a.check_in_at, a.check_out_at) for a in attendance_rows],
        "overtime": [(o.attendance_id, o.approved_hours) for o in overtime_rows],
        "leave": [(l.worker_id, l.leave_type, l.start_date, l.end_date) for l in leaves],
        "loans": [(l.id, l.outstanding_mmk, l.monthly_repayment_mmk) for l in loans],
        "claims": [(c.id, c.amount_mmk, c.claim_date) for c in claims],
        "adjustments": [(a.id, a.amount_mmk, a.status) for a in adjustments],
        "profiles": [
            (p.worker_id, p.join_date, p.final_working_date)
            for p in db.scalars(select(EmployeeProfile).where(
                EmployeeProfile.worker_id.in_(worker_ids or [""])
            )).all()
        ],
        "policies": [(p.key, p.value) for p in policies],
    }
    source = json.dumps(data, default=str, sort_keys=True).encode("utf-8")
    return hashlib.sha256(source).hexdigest()


@router.get("/dashboard", tags=["Dashboard"])
def dashboard(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    company_id = require_company(user)
    today = date.today()
    workers = payroll_workers(db, company_id, start, end)
    attendance = db.scalars(select(Attendance).where(
        Attendance.company_id == company_id, Attendance.work_date == today
    )).all()
    sites = db.scalars(select(Site).where(
        Site.company_id == company_id, Site.is_active.is_(True)
    )).all()
    pending_leave = db.scalar(select(LeaveRequest.id).where(
        LeaveRequest.company_id == company_id, LeaveRequest.status == "PENDING"
    ).limit(1))
    pending_claims = db.scalar(select(ExpenseClaim.id).where(
        ExpenseClaim.company_id == company_id, ExpenseClaim.status == "PENDING"
    ).limit(1))
    pending_evidence = db.scalar(select(AttendanceEvidence.id).where(
        AttendanceEvidence.company_id == company_id,
        AttendanceEvidence.review_status == "PENDING",
    ).limit(1))
    return {
        "as_of": today,
        "active_employees": len(workers),
        "active_sites": len(sites),
        "present_today": sum(a.attendance_status in ("PRESENT", "LATE") for a in attendance),
        "absent_today": sum(a.attendance_status == "ABSENT" for a in attendance),
        "attendance_records_today": len(attendance),
        "pending_leave_requests": int(pending_leave is not None),
        "pending_expense_claims": int(pending_claims is not None),
        "pending_photo_reviews": int(pending_evidence is not None),
    }


@router.put("/workers/{worker_id}/profile", tags=["Employee Directory"])
def update_employee_profile(
    worker_id: str, payload: EmployeeProfileInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "MANAGER", "HR")),
):
    company_id = require_company(user)
    get_worker(db, company_id, worker_id)
    profile = db.get(EmployeeProfile, worker_id)
    if not profile:
        profile = EmployeeProfile(worker_id=worker_id)
        db.add(profile)
    for key, value in payload.model_dump().items():
        setattr(profile, key, value)
    profile.updated_at = datetime.now(timezone.utc)
    audit(db, company_id, user, "employee.profile.updated", "employee", worker_id)
    db.commit()
    return {"worker_id": worker_id, **payload.model_dump(mode="json")}


@router.get("/workers/{worker_id}/profile", tags=["Employee Directory"])
def read_employee_profile(
    worker_id: str, db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    worker = get_worker(db, company_id, worker_id)
    profile = db.get(EmployeeProfile, worker_id)
    return {
        "worker_id": worker.id,
        "employee_code": worker.employee_code,
        "full_name": worker.full_name,
        "phone": worker.phone,
        "site_id": worker.site_id,
        "monthly_salary_mmk": worker.monthly_salary_mmk,
        **(EmployeeProfileInput.model_validate(profile, from_attributes=True).model_dump(mode="json") if profile else {}),
    }


@router.post("/workers/{worker_id}/records", status_code=201, tags=["Employee Directory"])
def add_employee_record(
    worker_id: str, payload: EmployeeRecordInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "MANAGER", "HR")),
):
    company_id = require_company(user)
    get_worker(db, company_id, worker_id)
    if payload.expires_on and payload.issued_on and payload.expires_on < payload.issued_on:
        raise HTTPException(422, "Expiry date cannot precede issue date")
    record = EmployeeRecord(
        company_id=company_id, worker_id=worker_id, created_by=user.id,
        **payload.model_dump(),
    )
    db.add(record)
    audit(db, company_id, user, "employee.record.added", "employee_record", record.id)
    db.commit()
    return {"id": record.id, **payload.model_dump(mode="json")}


@router.get("/workers/{worker_id}/records", tags=["Employee Directory"])
def list_employee_records(
    worker_id: str, db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    get_worker(db, company_id, worker_id)
    require_worker_access(db, company_id, user, worker_id)
    rows = db.scalars(select(EmployeeRecord).where(
        EmployeeRecord.company_id == company_id,
        EmployeeRecord.worker_id == worker_id,
    ).order_by(EmployeeRecord.expires_on)).all()
    return [{
        "id": row.id, "category": row.category, "title": row.title,
        "reference_number": row.reference_number, "issued_on": row.issued_on,
        "expires_on": row.expires_on, "evidence_url": row.evidence_url,
        "note": row.note,
    } for row in rows]


@router.put("/workers/{worker_id}/account", tags=["Employee Directory"])
def link_employee_account(
    worker_id: str, payload: AccountLinkInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "HR")),
):
    company_id = require_company(user)
    get_worker(db, company_id, worker_id)
    account = db.scalar(select(User).where(
        User.id == payload.user_id,
        User.company_id == company_id,
        User.role == "GUARD",
        User.is_active.is_(True),
    ))
    if not account:
        raise HTTPException(404, "Active guard account not found in this company")
    existing = db.scalar(select(EmployeeProfile).where(
        EmployeeProfile.user_id == account.id
    ))
    if existing and existing.worker_id != worker_id:
        raise HTTPException(409, "Account is already linked to another employee")
    profile = db.get(EmployeeProfile, worker_id)
    if not profile:
        profile = EmployeeProfile(worker_id=worker_id)
        db.add(profile)
    profile.user_id = account.id
    audit(db, company_id, user, "employee.account.linked", "employee", worker_id)
    db.commit()
    return {"worker_id": worker_id, "user_id": account.id}


@router.post("/workers/{worker_id}/self-service-account", status_code=201, tags=["Employee Self-Service"])
def create_guard_account(
    worker_id: str, payload: GuardAccountInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "HR")),
):
    company_id = require_company(user)
    get_worker(db, company_id, worker_id)
    duplicate = db.scalar(select(User).where(
        (User.username == payload.username) | (User.email == str(payload.email))
    ))
    if duplicate:
        raise HTTPException(409, "Username or email already exists")
    profile = db.get(EmployeeProfile, worker_id)
    if profile and profile.user_id:
        raise HTTPException(409, "Employee already has a self-service account")
    account = User(
        username=payload.username,
        email=str(payload.email),
        password_hash=hash_password(payload.password),
        role="GUARD",
        company_id=company_id,
        is_active=True,
    )
    db.add(account)
    db.flush()
    if not profile:
        profile = EmployeeProfile(worker_id=worker_id)
        db.add(profile)
    profile.user_id = account.id
    audit(db, company_id, user, "employee.self_service_account.created", "employee", worker_id)
    db.commit()
    return {"worker_id": worker_id, "username": account.username, "role": account.role}


@router.post("/workers/{worker_id}/site-assignments", status_code=201, tags=["Employee Directory"])
def assign_site(
    worker_id: str, payload: AssignmentInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "MANAGER", "HR")),
):
    company_id = require_company(user)
    worker = get_worker(db, company_id, worker_id)
    site = get_site(db, company_id, payload.site_id)
    if not site.is_active:
        raise HTTPException(422, "Cannot assign an inactive site")
    current = db.scalars(select(SiteAssignment).where(
        SiteAssignment.company_id == company_id,
        SiteAssignment.worker_id == worker_id,
        SiteAssignment.effective_to.is_(None),
    )).all()
    for assignment in current:
        if assignment.effective_from >= payload.effective_from:
            raise HTTPException(409, "Assignment effective date must follow the current assignment")
        assignment.effective_to = payload.effective_from - timedelta(days=1)
    assignment = SiteAssignment(
        company_id=company_id, worker_id=worker_id, site_id=site.id,
        effective_from=payload.effective_from, created_by=user.id,
    )
    worker.site_id = site.id
    db.add(assignment)
    audit(db, company_id, user, "employee.site.assigned", "site_assignment", assignment.id, {"site_id": site.id})
    db.commit()
    return {"id": assignment.id, "worker_id": worker_id, "site_id": site.id, "effective_from": assignment.effective_from}


@router.get("/workers/{worker_id}/site-assignments", tags=["Employee Directory"])
def assignment_history(
    worker_id: str, db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    get_worker(db, company_id, worker_id)
    rows = db.scalars(select(SiteAssignment).where(
        SiteAssignment.company_id == company_id,
        SiteAssignment.worker_id == worker_id,
    ).order_by(SiteAssignment.effective_from.desc())).all()
    return [{"id": r.id, "site_id": r.site_id, "effective_from": r.effective_from, "effective_to": r.effective_to} for r in rows]


@router.put("/workers/{worker_id}/salary-history", tags=["Salary Structures"])
@router.post("/workers/{worker_id}/salary-history", status_code=201, tags=["Salary Structures"])
def set_salary(
    worker_id: str, payload: SalaryInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PAYROLL", "HR")),
):
    company_id = require_company(user)
    worker = get_worker(db, company_id, worker_id)
    salary_records = db.scalars(select(SalaryHistory).where(
        SalaryHistory.company_id == company_id,
        SalaryHistory.worker_id == worker_id,
    )).all()
    if not salary_records:
        db.add(SalaryHistory(
            company_id=company_id,
            worker_id=worker_id,
            wage_basis="MONTHLY",
            base_rate_mmk=worker.monthly_salary_mmk,
            fixed_allowance_mmk=0,
            salary_grade="",
            effective_from=date.min,
            effective_to=payload.effective_from - timedelta(days=1),
            approved_by=user.id,
            note="Starting salary imported from employee record",
        ))
    current = db.scalars(select(SalaryHistory).where(
        SalaryHistory.company_id == company_id, SalaryHistory.worker_id == worker_id,
        SalaryHistory.effective_to.is_(None),
    )).all()
    for item in current:
        if item.effective_from >= payload.effective_from:
            raise HTTPException(409, "Salary effective date must follow the current salary")
        item.effective_to = payload.effective_from - timedelta(days=1)
    record = SalaryHistory(
        company_id=company_id, worker_id=worker_id, approved_by=user.id,
        **payload.model_dump(),
    )
    db.add(record)
    if payload.wage_basis == "MONTHLY":
        worker.monthly_salary_mmk = payload.base_rate_mmk
    audit(db, company_id, user, "salary.changed", "salary_history", record.id, {"effective_from": payload.effective_from})
    db.commit()
    return {"id": record.id, **payload.model_dump(mode="json")}


@router.get("/workers/{worker_id}/salary-history", tags=["Salary Structures"])
def salary_history(
    worker_id: str, db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    get_worker(db, company_id, worker_id)
    rows = db.scalars(select(SalaryHistory).where(
        SalaryHistory.company_id == company_id, SalaryHistory.worker_id == worker_id
    ).order_by(SalaryHistory.effective_from.desc())).all()
    return [{"id": r.id, "wage_basis": r.wage_basis, "base_rate_mmk": r.base_rate_mmk, "fixed_allowance_mmk": r.fixed_allowance_mmk, "salary_grade": r.salary_grade, "effective_from": r.effective_from, "effective_to": r.effective_to, "note": r.note} for r in rows]


@router.post("/shifts", status_code=201, tags=["Duty Roster"])
def create_shift(
    payload: ShiftInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "MANAGER")),
):
    company_id = require_company(user)
    existing = db.scalar(select(WorkShift.id).where(
        WorkShift.company_id == company_id,
        WorkShift.name == payload.name,
    ))
    if existing:
        raise HTTPException(409, "A shift with this name already exists")
    shift = WorkShift(company_id=company_id, **payload.model_dump())
    db.add(shift)
    audit(db, company_id, user, "shift.created", "shift", shift.id)
    db.commit()
    db.refresh(shift)
    return {"id": shift.id, **payload.model_dump()}


@router.get("/shifts", tags=["Duty Roster"])
def list_shifts(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    company_id = require_company(user)
    rows = db.scalars(select(WorkShift).where(
        WorkShift.company_id == company_id, WorkShift.is_active.is_(True)
    ).order_by(WorkShift.start_time)).all()
    return [{"id": s.id, "name": s.name, "start_time": s.start_time, "end_time": s.end_time, "scheduled_hours": s.scheduled_hours, "night_allowance_mmk": s.night_allowance_mmk} for s in rows]


@router.post("/roster", status_code=201, tags=["Duty Roster"])
def create_roster(
    payload: RosterInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "MANAGER", "SUPERVISOR")),
):
    company_id = require_company(user)
    worker = get_worker(db, company_id, payload.worker_id)
    site = get_site(db, company_id, payload.site_id)
    shift = db.scalar(select(WorkShift).where(
        WorkShift.id == payload.shift_id, WorkShift.company_id == company_id,
        WorkShift.is_active.is_(True),
    ))
    if not worker.is_active or not site.is_active or not shift:
        raise HTTPException(422, "Worker, site, or shift is inactive or invalid")
    if worker.site_id and worker.site_id != site.id:
        raise HTTPException(422, "Worker is not assigned to this site")
    existing_assignment = db.scalar(select(RosterAssignment.id).where(
        RosterAssignment.company_id == company_id,
        RosterAssignment.worker_id == worker.id,
        RosterAssignment.shift_date == payload.shift_date,
        RosterAssignment.status.in_(("SCHEDULED", "SWAPPED")),
    ))
    if existing_assignment:
        raise HTTPException(409, "Guard already has a scheduled shift on this date")
    assignment = RosterAssignment(company_id=company_id, created_by=user.id, **payload.model_dump())
    db.add(assignment)
    audit(db, company_id, user, "roster.created", "roster_assignment", assignment.id)
    db.commit()
    return {"id": assignment.id, **payload.model_dump(mode="json"), "status": assignment.status}


@router.post("/roster/{assignment_id}/swap-requests", status_code=201, tags=["Duty Roster"])
def request_shift_swap(
    assignment_id: str, replacement_worker_id: str,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    assignment = db.scalar(select(RosterAssignment).where(
        RosterAssignment.id == assignment_id,
        RosterAssignment.company_id == company_id,
        RosterAssignment.status == "SCHEDULED",
    ))
    if not assignment:
        raise HTTPException(404, "Scheduled assignment not found")
    require_worker_access(db, company_id, user, assignment.worker_id)
    replacement = get_worker(db, company_id, replacement_worker_id)
    if not replacement.is_active or (replacement.site_id and replacement.site_id != assignment.site_id):
        raise HTTPException(422, "Replacement guard is inactive or assigned to another site")
    request = ShiftSwapRequest(
        company_id=company_id, roster_assignment_id=assignment_id,
        requesting_worker_id=assignment.worker_id,
        replacement_worker_id=replacement_worker_id,
    )
    db.add(request)
    audit(db, company_id, user, "roster.swap.requested", "shift_swap_request", request.id)
    db.commit()
    return {"id": request.id, "status": request.status}


@router.post("/roster/swap-requests/{request_id}/review", tags=["Duty Roster"])
def review_shift_swap(
    request_id: str, payload: ReviewInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "MANAGER", "SUPERVISOR")),
):
    company_id = require_company(user)
    request = db.scalar(select(ShiftSwapRequest).where(
        ShiftSwapRequest.id == request_id,
        ShiftSwapRequest.company_id == company_id,
    ))
    if not request:
        raise HTTPException(404, "Shift swap request not found")
    if request.status != "PENDING":
        raise HTTPException(409, "Only pending requests can be reviewed")
    request.status = payload.status
    request.reviewed_by = user.id
    if payload.status == "APPROVED":
        assignment = db.get(RosterAssignment, request.roster_assignment_id)
        if not assignment or assignment.status != "SCHEDULED":
            raise HTTPException(409, "The roster assignment is no longer available")
        replacement_conflict = db.scalar(select(RosterAssignment.id).where(
            RosterAssignment.company_id == company_id,
            RosterAssignment.worker_id == request.replacement_worker_id,
            RosterAssignment.shift_date == assignment.shift_date,
            RosterAssignment.status.in_(("SCHEDULED", "SWAPPED")),
            RosterAssignment.id != assignment.id,
        ))
        if replacement_conflict:
            raise HTTPException(409, "Replacement guard already has a shift on that date")
        assignment.replacement_worker_id = request.replacement_worker_id
        assignment.status = "SWAPPED"
    audit(db, company_id, user, f"roster.swap.{payload.status.lower()}", "shift_swap_request", request.id, {"note": payload.note})
    db.commit()
    return {"id": request.id, "status": request.status}


@router.get("/roster", tags=["Duty Roster"])
def list_roster(
    start_date: date, end_date: date, site_id: Optional[str] = None,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    if end_date < start_date or (end_date - start_date).days > 93:
        raise HTTPException(422, "Date range must be valid and no longer than 93 days")
    query = select(RosterAssignment).where(
        RosterAssignment.company_id == company_id,
        RosterAssignment.shift_date.between(start_date, end_date),
    )
    if site_id:
        get_site(db, company_id, site_id)
        query = query.where(RosterAssignment.site_id == site_id)
    rows = db.scalars(query.order_by(RosterAssignment.shift_date)).all()
    return [{"id": a.id, "worker_id": a.worker_id, "site_id": a.site_id, "shift_id": a.shift_id, "shift_date": a.shift_date, "status": a.status, "replacement_worker_id": a.replacement_worker_id} for a in rows]


@router.post("/leave-requests", status_code=201, tags=["Leave Management"])
def request_leave(
    payload: LeaveInput, db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    get_worker(db, company_id, payload.worker_id)
    require_worker_access(db, company_id, user, payload.worker_id)
    if payload.end_date < payload.start_date:
        raise HTTPException(422, "End date cannot precede start date")
    overlap = db.scalar(select(LeaveRequest.id).where(
        LeaveRequest.company_id == company_id,
        LeaveRequest.worker_id == payload.worker_id,
        LeaveRequest.status.in_(("PENDING", "APPROVED")),
        LeaveRequest.start_date <= payload.end_date,
        LeaveRequest.end_date >= payload.start_date,
    ))
    if overlap:
        raise HTTPException(409, "Leave request overlaps an existing pending or approved request")
    leave = LeaveRequest(company_id=company_id, **payload.model_dump())
    db.add(leave)
    audit(db, company_id, user, "leave.requested", "leave_request", leave.id)
    db.commit()
    return {"id": leave.id, "status": leave.status, **payload.model_dump(mode="json")}


@router.get("/leave-requests", tags=["Leave Management"])
def list_leave(
    status_filter: Optional[Literal["PENDING", "APPROVED", "REJECTED"]] = None,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    query = select(LeaveRequest).where(LeaveRequest.company_id == company_id)
    if user.role == "GUARD":
        profile = db.scalar(select(EmployeeProfile).where(
            EmployeeProfile.user_id == user.id
        ))
        query = query.where(LeaveRequest.worker_id == (profile.worker_id if profile else ""))
    if status_filter:
        query = query.where(LeaveRequest.status == status_filter)
    rows = db.scalars(query.order_by(LeaveRequest.start_date.desc()).limit(200)).all()
    return [{"id": r.id, "worker_id": r.worker_id, "leave_type": r.leave_type, "start_date": r.start_date, "end_date": r.end_date, "reason": r.reason, "status": r.status} for r in rows]


@router.post("/leave-requests/{request_id}/review", tags=["Leave Management"])
def review_leave(
    request_id: str, payload: ReviewInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "MANAGER", "HR")),
):
    company_id = require_company(user)
    leave = db.scalar(select(LeaveRequest).where(
        LeaveRequest.id == request_id, LeaveRequest.company_id == company_id
    ))
    if not leave:
        raise HTTPException(404, "Leave request not found")
    if leave.status != "PENDING":
        raise HTTPException(409, "Only pending leave requests can be reviewed")
    leave.status = payload.status
    leave.reviewed_by = user.id
    leave.reviewed_at = datetime.now(timezone.utc)
    audit(db, company_id, user, f"leave.{payload.status.lower()}", "leave_request", leave.id, {"note": payload.note})
    db.commit()
    return {"id": leave.id, "status": leave.status}


@router.put("/workers/{worker_id}/leave-entitlements/{leave_type}/{year}", tags=["Leave Management"])
def set_leave_entitlement(
    worker_id: str, leave_type: Literal["ANNUAL", "CASUAL", "MEDICAL", "UNPAID", "MATERNITY", "PATERNITY", "OTHER"],
    year: int, payload: LeaveEntitlementInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "HR")),
):
    company_id = require_company(user)
    get_worker(db, company_id, worker_id)
    if year < 2000 or year > 2100:
        raise HTTPException(422, "Year must be between 2000 and 2100")
    entitlement = db.scalar(select(LeaveEntitlement).where(
        LeaveEntitlement.company_id == company_id,
        LeaveEntitlement.worker_id == worker_id,
        LeaveEntitlement.leave_type == leave_type,
        LeaveEntitlement.year == year,
    ))
    if not entitlement:
        entitlement = LeaveEntitlement(
            company_id=company_id, worker_id=worker_id, leave_type=leave_type,
            year=year, updated_by=user.id, **payload.model_dump(),
        )
        db.add(entitlement)
    else:
        entitlement.entitlement_days = payload.entitlement_days
        entitlement.carryover_days = payload.carryover_days
        entitlement.updated_by = user.id
    audit(db, company_id, user, "leave.entitlement.updated", "leave_entitlement", entitlement.id)
    db.commit()
    return {"worker_id": worker_id, "leave_type": leave_type, "year": year, **payload.model_dump()}


@router.get("/workers/{worker_id}/leave-balances", tags=["Leave Management"])
def get_leave_balances(
    worker_id: str, year: int = Query(default=date.today().year, ge=2000, le=2100),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    get_worker(db, company_id, worker_id)
    require_worker_access(db, company_id, user, worker_id)
    entitlements = db.scalars(select(LeaveEntitlement).where(
        LeaveEntitlement.company_id == company_id,
        LeaveEntitlement.worker_id == worker_id,
        LeaveEntitlement.year == year,
    )).all()
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    approved = db.scalars(select(LeaveRequest).where(
        LeaveRequest.company_id == company_id,
        LeaveRequest.worker_id == worker_id,
        LeaveRequest.status == "APPROVED",
        LeaveRequest.start_date <= year_end,
        LeaveRequest.end_date >= year_start,
    )).all()
    used_by_type: dict[str, int] = {}
    for leave in approved:
        overlap_start = max(leave.start_date, year_start)
        overlap_end = min(leave.end_date, year_end)
        used_by_type[leave.leave_type] = used_by_type.get(leave.leave_type, 0) + (overlap_end - overlap_start).days + 1
    return [{
        "leave_type": entitlement.leave_type,
        "year": year,
        "entitlement_days": entitlement.entitlement_days,
        "carryover_days": entitlement.carryover_days,
        "used_days": used_by_type.get(entitlement.leave_type, 0),
        "remaining_days": max(
            0,
            entitlement.entitlement_days + entitlement.carryover_days
            - used_by_type.get(entitlement.leave_type, 0),
        ),
    } for entitlement in entitlements]


@router.post("/attendance/{attendance_id}/evidence", status_code=201, tags=["Photo Attendance"])
def add_attendance_evidence(
    attendance_id: str, payload: EvidenceInput, db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    attendance = db.scalar(select(Attendance).where(
        Attendance.id == attendance_id, Attendance.company_id == company_id
    ))
    if not attendance:
        raise HTTPException(404, "Attendance record not found")
    require_worker_access(db, company_id, user, attendance.worker_id)
    if policy_value(db, company_id, "photo_attendance_enabled", "true").lower() != "true":
        raise HTTPException(403, "Photo attendance is disabled by company policy")
    if payload.ocr_text and policy_value(db, company_id, "ocr_enabled", "false").lower() != "true":
        raise HTTPException(403, "OCR is disabled by company policy")
    if (payload.latitude is not None or payload.longitude is not None) and (
        not payload.gps_consent or policy_value(db, company_id, "gps_attendance_enabled", "false").lower() != "true"
    ):
        raise HTTPException(403, "GPS capture requires user consent and enabled company policy")
    evidence = AttendanceEvidence(company_id=company_id, attendance_id=attendance_id, **payload.model_dump())
    db.add(evidence)
    audit(db, company_id, user, "attendance.evidence.added", "attendance_evidence", evidence.id)
    db.commit()
    return {"id": evidence.id, "attendance_id": attendance_id, "review_status": evidence.review_status}


@router.post("/attendance/periods/{year}/{month}/lock", tags=["Attendance Calculation"])
def lock_attendance_period(
    year: int, month: int, payload: PeriodReasonInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "MANAGER", "PAYROLL")),
):
    company_id = require_company(user)
    if month < 1 or month > 12 or year < 2020 or year > 2100:
        raise HTTPException(422, "Invalid attendance period")
    pending_evidence = db.scalar(select(AttendanceEvidence.id).join(
        Attendance, Attendance.id == AttendanceEvidence.attendance_id
    ).where(
        AttendanceEvidence.company_id == company_id,
        AttendanceEvidence.review_status == "PENDING",
        Attendance.work_date.between(
            date(year, month, 1),
            date(year, month, calendar.monthrange(year, month)[1]),
        ),
    ).limit(1))
    if pending_evidence:
        raise HTTPException(409, "Review pending photo evidence before locking attendance")
    pending_correction = db.scalar(select(AttendanceCorrection.id).join(
        Attendance, Attendance.id == AttendanceCorrection.attendance_id
    ).where(
        AttendanceCorrection.company_id == company_id,
        AttendanceCorrection.status == "PENDING",
        Attendance.work_date.between(
            date(year, month, 1),
            date(year, month, calendar.monthrange(year, month)[1]),
        ),
    ).limit(1))
    if pending_correction:
        raise HTTPException(409, "Review pending attendance corrections before locking")
    lock = db.scalar(select(AttendancePeriodLock).where(
        AttendancePeriodLock.company_id == company_id,
        AttendancePeriodLock.year == year,
        AttendancePeriodLock.month == month,
    ))
    if lock:
        raise HTTPException(409, "Attendance period is already locked")
    lock = AttendancePeriodLock(
        company_id=company_id, year=year, month=month,
        locked_by=user.id, reason=payload.reason,
    )
    db.add(lock)
    audit(db, company_id, user, "attendance.period.locked", "attendance_period", f"{year}-{month:02d}", {"reason": payload.reason})
    db.commit()
    return {"year": year, "month": month, "status": "LOCKED", "locked_by": user.id, "locked_at": lock.locked_at}


@router.post("/attendance/{attendance_id}/corrections", status_code=201, tags=["Attendance Calculation"])
def request_attendance_correction(
    attendance_id: str, payload: AttendanceCorrectionInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "MANAGER", "SUPERVISOR")),
):
    company_id = require_company(user)
    attendance = db.scalar(select(Attendance).where(
        Attendance.id == attendance_id,
        Attendance.company_id == company_id,
    ))
    if not attendance:
        raise HTTPException(404, "Attendance record not found")
    values = payload.model_dump(exclude={"reason"}, exclude_none=True)
    if not values:
        raise HTTPException(422, "At least one attendance field must be corrected")
    if "site_id" in values:
        target_site = get_site(db, company_id, values["site_id"])
        if not target_site.is_active:
            raise HTTPException(422, "Corrected site must be active")
    start = values.get("check_in_at", attendance.check_in_at)
    end = values.get("check_out_at", attendance.check_out_at)
    if start and end and end < start:
        raise HTTPException(422, "Check-out cannot be earlier than check-in")
    correction = AttendanceCorrection(
        company_id=company_id, attendance_id=attendance_id,
        changes_json=json.dumps(values, default=str),
        reason=payload.reason, requested_by=user.id,
    )
    db.add(correction)
    audit(db, company_id, user, "attendance.correction.requested", "attendance_correction", correction.id, {"reason": payload.reason})
    db.commit()
    return {"id": correction.id, "status": correction.status}


@router.post("/attendance/corrections/{correction_id}/review", tags=["Attendance Calculation"])
def review_attendance_correction(
    correction_id: str, payload: ReviewInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "MANAGER", "SUPERVISOR")),
):
    company_id = require_company(user)
    correction = db.scalar(select(AttendanceCorrection).where(
        AttendanceCorrection.id == correction_id,
        AttendanceCorrection.company_id == company_id,
    ))
    if not correction:
        raise HTTPException(404, "Attendance correction not found")
    if correction.status != "PENDING":
        raise HTTPException(409, "Only pending corrections can be reviewed")
    if correction.requested_by == user.id:
        raise HTTPException(403, "Correction requester cannot approve their own request")
    correction.status = payload.status
    correction.reviewed_by = user.id
    correction.reviewed_at = datetime.now(timezone.utc)
    if payload.status == "APPROVED":
        attendance = db.get(Attendance, correction.attendance_id)
        payroll_period = db.scalar(select(PayrollPeriod).where(
            PayrollPeriod.company_id == company_id,
            PayrollPeriod.year == attendance.work_date.year,
            PayrollPeriod.month == attendance.work_date.month,
        ))
        if payroll_period and payroll_period.status in (
            "PENDING_APPROVAL", "APPROVED", "PAID", "LOCKED"
        ):
            raise HTTPException(409, "Payroll has advanced; use an authorized payroll adjustment instead")
        for key, value in json.loads(correction.changes_json).items():
            if key in ("check_in_at", "check_out_at") and value:
                value = datetime.fromisoformat(value)
            setattr(attendance, key, value)
    audit(db, company_id, user, f"attendance.correction.{payload.status.lower()}", "attendance_correction", correction.id, {"reason": payload.note})
    db.commit()
    return {"id": correction.id, "status": correction.status, "reviewed_by": correction.reviewed_by}


@router.put("/attendance/{attendance_id}/overtime", tags=["Attendance Calculation"])
def approve_overtime(
    attendance_id: str, payload: OvertimeInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "MANAGER", "SUPERVISOR", "PAYROLL")),
):
    company_id = require_company(user)
    attendance = db.scalar(select(Attendance).where(
        Attendance.id == attendance_id, Attendance.company_id == company_id
    ))
    if not attendance:
        raise HTTPException(404, "Attendance record not found")
    if attendance.attendance_status not in ("PRESENT", "LATE"):
        raise HTTPException(422, "Overtime can only be approved for present attendance")
    overtime = db.scalar(select(ApprovedOvertime).where(
        ApprovedOvertime.company_id == company_id,
        ApprovedOvertime.attendance_id == attendance_id,
    ))
    if not overtime:
        overtime = ApprovedOvertime(
            company_id=company_id, attendance_id=attendance_id,
            approved_hours=payload.approved_hours, approved_by=user.id,
        )
        db.add(overtime)
    else:
        overtime.approved_hours = payload.approved_hours
        overtime.approved_by = user.id
        overtime.approved_at = datetime.now(timezone.utc)
    audit(db, company_id, user, "attendance.overtime.approved", "attendance", attendance_id, {"hours": payload.approved_hours})
    db.commit()
    return {"attendance_id": attendance_id, "approved_hours": payload.approved_hours}


@router.get("/attendance/evidence", tags=["Photo Attendance"])
def list_evidence(
    review_status: Optional[Literal["PENDING", "APPROVED", "REJECTED"]] = None,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    query = select(AttendanceEvidence).where(AttendanceEvidence.company_id == company_id)
    if review_status:
        query = query.where(AttendanceEvidence.review_status == review_status)
    if user.role == "GUARD":
        profile = db.scalar(select(EmployeeProfile).where(
            EmployeeProfile.user_id == user.id
        ))
        if not profile:
            return []
        query = query.join(
            Attendance, Attendance.id == AttendanceEvidence.attendance_id
        ).where(Attendance.worker_id == profile.worker_id)
    rows = db.scalars(query.order_by(AttendanceEvidence.created_at.desc()).limit(200)).all()
    return [{"id": e.id, "attendance_id": e.attendance_id, "photo_url": e.photo_url, "latitude": e.latitude, "longitude": e.longitude, "gps_consent": e.gps_consent, "ocr_text": e.ocr_text, "review_status": e.review_status} for e in rows]


@router.post("/attendance/evidence/{evidence_id}/review", tags=["Photo Attendance"])
def review_evidence(
    evidence_id: str, payload: ReviewInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "MANAGER", "SUPERVISOR")),
):
    company_id = require_company(user)
    evidence = db.scalar(select(AttendanceEvidence).where(
        AttendanceEvidence.id == evidence_id, AttendanceEvidence.company_id == company_id
    ))
    if not evidence:
        raise HTTPException(404, "Attendance evidence not found")
    if evidence.review_status != "PENDING":
        raise HTTPException(409, "Only pending evidence can be reviewed")
    evidence.review_status = payload.status
    evidence.reviewed_by = user.id
    audit(db, company_id, user, "attendance.evidence.reviewed", "attendance_evidence", evidence.id, {"status": payload.status, "note": payload.note})
    db.commit()
    return {"id": evidence.id, "review_status": evidence.review_status}


@router.post("/payroll/calculate", tags=["Payroll Processing"])
def calculate_period(
    year: int = Query(ge=2020, le=2100), month: int = Query(ge=1, le=12),
    recalculate: bool = Query(default=False),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PAYROLL")),
):
    company_id = require_company(user)
    from app.subscriptions import assert_subscription_access

    assert_subscription_access(db, company_id, feature="payroll")
    if db.bind and db.bind.dialect.name == "postgresql":
        lock_material = f"{company_id}:{year}:{month}".encode("utf-8")
        lock_key = int.from_bytes(hashlib.sha256(lock_material).digest()[:8], "big", signed=True)
        db.execute(select(func.pg_advisory_xact_lock(lock_key)))
    if idempotency_key is not None:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key or len(idempotency_key) > 120:
            raise HTTPException(422, "Idempotency-Key must contain 1 to 120 characters")
        prior_request = db.scalar(select(PayrollRunRequest).where(
            PayrollRunRequest.company_id == company_id,
            PayrollRunRequest.idempotency_key == idempotency_key,
        ))
        if prior_request:
            if (prior_request.year, prior_request.month) != (year, month):
                raise HTTPException(409, "Idempotency-Key was already used for another payroll period")
            return json.loads(prior_request.response_json)
    try:
        working_days = int(policy_value(db, company_id, "working_days_per_month", "26"))
        hours_per_day = float(policy_value(db, company_id, "hours_per_day", "8"))
        overtime_multiplier = float(policy_value(db, company_id, "overtime_multiplier", "1.5"))
    except ValueError as exc:
        raise HTTPException(422, "Company payroll policies contain invalid numeric values") from exc
    if not 1 <= working_days <= 31 or not 1 <= hours_per_day <= 24 or not 1 <= overtime_multiplier <= 5:
        raise HTTPException(422, "Invalid company payroll policy values")
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    attendance_lock = db.scalar(select(AttendancePeriodLock).where(
        AttendancePeriodLock.company_id == company_id,
        AttendancePeriodLock.year == year,
        AttendancePeriodLock.month == month,
    ))
    if not attendance_lock:
        raise HTTPException(
            409,
            "Attendance must be reviewed and locked before payroll calculation",
        )
    period = db.scalar(select(PayrollPeriod).where(
        PayrollPeriod.company_id == company_id,
        PayrollPeriod.year == year,
        PayrollPeriod.month == month,
    ).with_for_update())
    if period and period.status not in ("DRAFT", "CALCULATED"):
        raise HTTPException(409, f"Payroll period is {period.status} and cannot be recalculated")
    if not period:
        period = PayrollPeriod(company_id=company_id, year=year, month=month)
        db.add(period)
        db.flush()
    fingerprint = payroll_fingerprint(db, company_id, start, end)
    if period.status == "CALCULATED" and period.input_fingerprint == fingerprint:
        existing_rows = db.scalars(select(Payroll).where(
            Payroll.company_id == company_id,
            Payroll.year == year,
            Payroll.month == month,
        ).order_by(Payroll.worker_id)).all()
        unchanged_response = {
            "year": year,
            "month": month,
            "version": period.version,
            "status": period.status,
            "recalculated": False,
            "working_days_policy": working_days,
            "results": [{
                "worker_id": record.worker_id,
                "payroll_id": record.id,
                "gross_pay_mmk": record.base_salary_mmk + record.allowance_mmk,
                "deductions_mmk": record.deduction_mmk,
                "net_pay_mmk": record.net_salary_mmk,
                "status": record.payroll_status,
            } for record in existing_rows],
        }
        if idempotency_key:
            db.add(PayrollRunRequest(
                company_id=company_id, idempotency_key=idempotency_key,
                year=year, month=month,
                response_json=json.dumps(unchanged_response, default=str),
            ))
            db.commit()
        return unchanged_response
    if period.status == "CALCULATED" and not recalculate:
        raise HTTPException(
            409,
            "Payroll inputs changed after calculation; set recalculate=true to create a new version",
        )
    workers = db.scalars(select(Worker).where(
        Worker.company_id == company_id, Worker.is_active.is_(True)
    )).all()
    results = []
    for worker in workers:
        profile = db.get(EmployeeProfile, worker.id)
        active_start = max(start, profile.join_date) if profile and profile.join_date else start
        active_end = min(end, profile.final_working_date) if profile and profile.final_working_date else end
        if active_start > active_end:
            continue
        payroll = db.scalar(select(Payroll).where(
            Payroll.company_id == company_id, Payroll.worker_id == worker.id,
            Payroll.year == year, Payroll.month == month,
        ))
        if payroll and payroll.payroll_status not in ("DRAFT", "CALCULATED"):
            results.append({"worker_id": worker.id, "status": payroll.payroll_status, "skipped": True})
            continue
        salary_rows = db.scalars(select(SalaryHistory).where(
            SalaryHistory.company_id == company_id,
            SalaryHistory.worker_id == worker.id,
            SalaryHistory.effective_from <= active_end,
            (SalaryHistory.effective_to.is_(None))
            | (SalaryHistory.effective_to >= active_start),
        ).order_by(SalaryHistory.effective_from)).all()
        salary = next(
            (item for item in reversed(salary_rows) if item.effective_from <= active_end),
            None,
        )
        basis = salary.wage_basis if salary else "MONTHLY"
        rate = salary.base_rate_mmk if salary else worker.monthly_salary_mmk
        allowance = salary.fixed_allowance_mmk if salary else 0
        attendance = db.scalars(select(Attendance).where(
            Attendance.company_id == company_id, Attendance.worker_id == worker.id,
            Attendance.work_date.between(start, end),
        )).all()
        worked = sum(a.attendance_status in ("PRESENT", "LATE") for a in attendance)
        unpaid_dates = {a.work_date for a in attendance if a.attendance_status == "ABSENT"}
        approved_unpaid_leaves = db.scalars(select(LeaveRequest).where(
            LeaveRequest.company_id == company_id,
            LeaveRequest.worker_id == worker.id,
            LeaveRequest.status == "APPROVED",
            LeaveRequest.leave_type == "UNPAID",
            LeaveRequest.start_date <= end,
            LeaveRequest.end_date >= start,
        )).all()
        for leave in approved_unpaid_leaves:
            leave_start = max(start, leave.start_date)
            leave_end = min(end, leave.end_date)
            unpaid_dates.update(
                leave_start + timedelta(days=day)
                for day in range((leave_end - leave_start).days + 1)
            )
        unpaid_days = len(unpaid_dates)
        attendance_ids = [a.id for a in attendance if a.attendance_status in ("PRESENT", "LATE")]
        approved_overtime_rows = db.scalars(select(ApprovedOvertime).where(
            ApprovedOvertime.company_id == company_id,
            ApprovedOvertime.attendance_id.in_(attendance_ids or [""]),
        )).all()
        overtime_by_attendance = {
            item.attendance_id: item.approved_hours for item in approved_overtime_rows
        }
        overtime_hours = sum(overtime_by_attendance.values())
        roster_rows = db.scalars(select(RosterAssignment).where(
            RosterAssignment.company_id == company_id,
            RosterAssignment.worker_id == worker.id,
            RosterAssignment.shift_date.between(active_start, active_end),
            RosterAssignment.status.in_(("SCHEDULED", "SWAPPED")),
        )).all()
        roster_by_date = {row.shift_date: row for row in roster_rows}
        shift_ids = [row.shift_id for row in roster_rows]
        shift_rows = db.scalars(select(WorkShift).where(
            WorkShift.company_id == company_id,
            WorkShift.id.in_(shift_ids or [""]),
        )).all()
        shift_by_id = {shift.id: shift for shift in shift_rows}
        attendance_by_date: dict[date, list[Attendance]] = {}
        for row in attendance:
            if row.attendance_status in ("PRESENT", "LATE"):
                attendance_by_date.setdefault(row.work_date, []).append(row)
        month_days = (end - start).days + 1
        base_amount = 0.0
        allowance_amount = 0.0
        overtime_pay = 0.0
        worked_hours = 0.0
        unpaid_deduction = 0.0
        salary_for_day = salary_rows
        current_day = active_start
        while current_day <= active_end:
            applicable = [
                item for item in salary_for_day
                if item.effective_from <= current_day
                and (item.effective_to is None or item.effective_to >= current_day)
            ]
            daily_salary = applicable[-1] if applicable else None
            daily_basis = daily_salary.wage_basis if daily_salary else "MONTHLY"
            daily_rate = daily_salary.base_rate_mmk if daily_salary else worker.monthly_salary_mmk
            daily_allowance = daily_salary.fixed_allowance_mmk if daily_salary else 0
            day_attendance = attendance_by_date.get(current_day, [])
            daily_shift = roster_by_date.get(current_day)
            configured_shift = shift_by_id.get(daily_shift.shift_id) if daily_shift else None
            allowance_amount += daily_allowance / month_days
            if daily_basis == "MONTHLY":
                base_amount += daily_rate / month_days
                hourly_rate = daily_rate / (max(working_days, 1) * hours_per_day)
                if current_day in unpaid_dates:
                    unpaid_deduction += hourly_rate * hours_per_day
            else:
                for entry in day_attendance:
                    elapsed = None
                    if entry.check_in_at and entry.check_out_at:
                        elapsed = (
                            entry.check_out_at - entry.check_in_at
                        ).total_seconds() / 3600
                    scheduled_hours = (
                        configured_shift.scheduled_hours
                        if configured_shift else hours_per_day
                    )
                    shift_hours = max(0, elapsed if elapsed is not None else scheduled_hours)
                    worked_hours += shift_hours
                    if daily_basis in ("DAILY", "SHIFT"):
                        base_amount += daily_rate
                        hourly_rate = daily_rate / max(hours_per_day, 1)
                    elif daily_basis == "HOURLY":
                        base_amount += daily_rate * shift_hours
                        hourly_rate = daily_rate
                    else:
                        raise HTTPException(422, f"Unsupported wage basis: {daily_basis}")
                    approved_hours = overtime_by_attendance.get(entry.id, 0)
                    overtime_pay += approved_hours * hourly_rate * overtime_multiplier
            if daily_basis == "MONTHLY":
                for entry in day_attendance:
                    approved_hours = overtime_by_attendance.get(entry.id, 0)
                    overtime_pay += approved_hours * hourly_rate * overtime_multiplier
                    if entry.check_in_at and entry.check_out_at:
                        worked_hours += max(
                            0,
                            (entry.check_out_at - entry.check_in_at).total_seconds() / 3600,
                        )
            current_day += timedelta(days=1)
        night_shifts = 0
        for record in attendance:
            night_shifts += (
                active_start <= record.work_date <= active_end
                and record.shift == "NIGHT"
                and record.attendance_status in ("PRESENT", "LATE")
            )
        scheduled_days = min(working_days, calendar.monthrange(year, month)[1])
        outstanding_loans = db.scalars(select(LoanAdvance).where(
            LoanAdvance.company_id == company_id, LoanAdvance.worker_id == worker.id,
            LoanAdvance.status == "APPROVED", LoanAdvance.outstanding_mmk > 0,
        )).all()
        repayment = min(
            sum(min(x.outstanding_mmk, x.monthly_repayment_mmk) for x in outstanding_loans),
            max(round(base_amount + allowance_amount), 0),
        )
        night_allowance = 0
        if night_shifts:
            try:
                night_allowance = int(policy_value(db, company_id, "night_shift_allowance_mmk", "0"))
            except ValueError as exc:
                raise HTTPException(422, "Night shift allowance policy must be a whole number") from exc
        components = calculate_payroll_amounts(
            wage_basis=basis, rate=rate, fixed_allowance=allowance,
            worked_days=worked if attendance else scheduled_days,
            scheduled_days=scheduled_days,
            worked_hours=worked_hours,
            overtime_hours=overtime_hours,
            night_shifts=night_shifts,
            night_allowance=night_allowance,
            overtime_multiplier=overtime_multiplier,
            loan_repayment=repayment,
            unpaid_leave_days=unpaid_days,
            active_calendar_days=(active_end - active_start).days + 1,
            period_calendar_days=(end - start).days + 1,
            base_override=round(base_amount),
            allowance_override=round(allowance_amount),
            overtime_pay_override=round(overtime_pay),
            unpaid_leave_deduction_override=round(unpaid_deduction),
        )
        approved_claims = db.scalars(select(ExpenseClaim).where(
            ExpenseClaim.company_id == company_id,
            ExpenseClaim.worker_id == worker.id,
            ExpenseClaim.status == "APPROVED",
            ExpenseClaim.claim_date.between(start, end),
        )).all()
        if approved_claims:
            components.append({
                "type": "EARNING",
                "code": "REIMBURSEMENT",
                "description": "Approved expense reimbursements",
                "amount_mmk": sum(claim.amount_mmk for claim in approved_claims),
            })
        approved_adjustments = db.scalars(select(PayrollAdjustment).where(
            PayrollAdjustment.company_id == company_id,
            PayrollAdjustment.effective_year == year,
            PayrollAdjustment.effective_month == month,
            PayrollAdjustment.status == "APPROVED",
        )).all()
        for adjustment in approved_adjustments:
            source_payroll = db.get(Payroll, adjustment.payroll_id)
            if source_payroll and source_payroll.worker_id == worker.id:
                components.append({
                    "type": "EARNING" if adjustment.amount_mmk > 0 else "DEDUCTION",
                    "code": "ADJUSTMENT",
                    "description": adjustment.reason,
                    "amount_mmk": abs(adjustment.amount_mmk),
                    "source_reference": adjustment.id,
                })
        try:
            deduction_cap = int(policy_value(db, company_id, "deduction_cap_mmk", "0"))
        except ValueError as exc:
            raise HTTPException(422, "Deduction cap policy must be a whole number") from exc
        current_deductions = sum(
            item["amount_mmk"] for item in components if item["type"] == "DEDUCTION"
        )
        if deduction_cap > 0 and current_deductions > deduction_cap:
            remaining_cap = deduction_cap
            for component in components:
                if component["type"] != "DEDUCTION":
                    continue
                allowed = min(component["amount_mmk"], remaining_cap)
                component["amount_mmk"] = allowed
                remaining_cap -= allowed
        gross, deductions, net = payroll_totals(components)
        if payroll is None:
            payroll = Payroll(
                company_id=company_id, worker_id=worker.id, year=year, month=month,
                base_salary_mmk=next((i["amount_mmk"] for i in components if i["code"] == "BASE"), 0),
                allowance_mmk=sum(i["amount_mmk"] for i in components if i["type"] == "EARNING" and i["code"] != "BASE"),
                deduction_mmk=deductions, net_salary_mmk=net, payroll_status="DRAFT",
            )
            db.add(payroll)
            db.flush()
        else:
            payroll.base_salary_mmk = next((i["amount_mmk"] for i in components if i["code"] == "BASE"), 0)
            payroll.allowance_mmk = sum(i["amount_mmk"] for i in components if i["type"] == "EARNING" and i["code"] != "BASE")
            payroll.deduction_mmk = deductions
            payroll.net_salary_mmk = net
            payroll.payroll_status = "CALCULATED"
            db.query(PayrollComponent).filter(
                PayrollComponent.company_id == company_id, PayrollComponent.payroll_id == payroll.id
            ).delete(synchronize_session=False)
        for component in components:
            db.add(PayrollComponent(
                company_id=company_id,
                payroll_id=payroll.id,
                component_type=component["type"],
                code=component["code"],
                description=component["description"],
                amount_mmk=component["amount_mmk"],
                source_reference=component.get("source_reference", ""),
            ))
        payroll.payroll_status = "CALCULATED"
        results.append({"worker_id": worker.id, "payroll_id": payroll.id, "gross_pay_mmk": gross, "deductions_mmk": deductions, "net_pay_mmk": net, "status": payroll.payroll_status})
    period.status = "CALCULATED"
    period.version += 1
    period.input_fingerprint = fingerprint
    period.calculated_at = datetime.now(timezone.utc)
    response = {
        "year": year,
        "month": month,
        "version": period.version,
        "status": period.status,
        "recalculated": recalculate and period.version > 1,
        "working_days_policy": working_days,
        "results": results,
    }
    if idempotency_key:
        db.add(PayrollRunRequest(
            company_id=company_id, idempotency_key=idempotency_key,
            year=year, month=month,
            response_json=json.dumps(response, default=str),
        ))
    audit(
        db, company_id, user,
        "payroll.period.recalculated" if period.version > 1 else "payroll.period.calculated",
        "payroll_period", period.id,
        {"employees": len(results), "version": period.version, "recalculate": recalculate},
    )
    db.commit()
    return response


@router.get("/payroll/periods", tags=["Payroll Processing"])
def list_payroll_periods(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    company_id = require_company(user)
    periods = db.scalars(select(PayrollPeriod).where(
        PayrollPeriod.company_id == company_id
    ).order_by(PayrollPeriod.year.desc(), PayrollPeriod.month.desc()).limit(120)).all()
    return [{
        "id": p.id, "year": p.year, "month": p.month, "status": p.status,
        "version": p.version, "calculated_at": p.calculated_at,
        "submitted_at": p.submitted_at, "approved_by": p.approved_by,
        "approved_at": p.approved_at, "approval_reason": p.approval_reason,
        "locked_by": p.locked_by, "locked_at": p.locked_at,
    } for p in periods]


@router.post("/payroll/periods/{year}/{month}/submit", tags=["Payroll Processing"])
def submit_payroll_period(
    year: int, month: int, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PAYROLL")),
):
    company_id = require_company(user)
    period = db.scalar(select(PayrollPeriod).where(
        PayrollPeriod.company_id == company_id,
        PayrollPeriod.year == year, PayrollPeriod.month == month,
    ))
    if not period:
        raise HTTPException(404, "Payroll period not found")
    if period.status != "CALCULATED":
        raise HTTPException(409, "Only a calculated payroll period can be submitted")
    records = db.scalars(select(Payroll).where(
        Payroll.company_id == company_id,
        Payroll.year == year, Payroll.month == month,
    )).all()
    if not records:
        raise HTTPException(409, "Cannot submit an empty payroll period")
    if any(record.payroll_status != "CALCULATED" for record in records):
        raise HTTPException(409, "Every payroll record must be calculated before submission")
    period.status = "PENDING_APPROVAL"
    period.submitted_at = datetime.now(timezone.utc)
    period.submitted_by = user.id
    audit(db, company_id, user, "payroll.period.submitted", "payroll_period", period.id, {"version": period.version})
    db.commit()
    return {"year": year, "month": month, "status": period.status, "version": period.version}


@router.post("/payroll/periods/{year}/{month}/approve", tags=["Payroll Processing"])
def approve_payroll_period(
    year: int, month: int, payload: PeriodReasonInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PAYROLL")),
):
    company_id = require_company(user)
    period = db.scalar(select(PayrollPeriod).where(
        PayrollPeriod.company_id == company_id,
        PayrollPeriod.year == year, PayrollPeriod.month == month,
    ))
    if not period:
        raise HTTPException(404, "Payroll period not found")
    if period.status != "PENDING_APPROVAL":
        raise HTTPException(409, "Only pending payroll periods can be approved")
    if period.submitted_by == user.id:
        raise HTTPException(403, "The payroll submitter cannot approve the same period")
    records = db.scalars(select(Payroll).where(
        Payroll.company_id == company_id,
        Payroll.year == year, Payroll.month == month,
    )).all()
    if not records:
        raise HTTPException(409, "Cannot approve an empty payroll period")
    for payroll in records:
        payroll.payroll_status = "PAID" if payroll.net_salary_mmk == 0 else "APPROVED"
        repayments = db.scalars(select(PayrollComponent).where(
            PayrollComponent.company_id == company_id,
            PayrollComponent.payroll_id == payroll.id,
            PayrollComponent.code == "LOAN_REPAYMENT",
        )).all()
        repayment_remaining = sum(row.amount_mmk for row in repayments)
        loans = db.scalars(select(LoanAdvance).where(
            LoanAdvance.company_id == company_id,
            LoanAdvance.worker_id == payroll.worker_id,
            LoanAdvance.status == "APPROVED",
            LoanAdvance.outstanding_mmk > 0,
        ).order_by(LoanAdvance.created_at)).all()
        for loan in loans:
            applied = min(repayment_remaining, loan.outstanding_mmk)
            loan.outstanding_mmk -= applied
            repayment_remaining -= applied
            if loan.outstanding_mmk == 0:
                loan.status = "PAID"
            if repayment_remaining == 0:
                break
        claims = db.scalars(select(ExpenseClaim).where(
            ExpenseClaim.company_id == company_id,
            ExpenseClaim.worker_id == payroll.worker_id,
            ExpenseClaim.status == "APPROVED",
            ExpenseClaim.claim_date.between(
                date(year, month, 1),
                date(year, month, calendar.monthrange(year, month)[1]),
            ),
        )).all()
        for claim in claims:
            claim.status = "REIMBURSED"
        adjustments = db.scalars(select(PayrollAdjustment).where(
            PayrollAdjustment.company_id == company_id,
            PayrollAdjustment.effective_year == year,
            PayrollAdjustment.effective_month == month,
            PayrollAdjustment.status == "APPROVED",
        )).all()
        for adjustment in adjustments:
            if adjustment.payroll_id:
                source_payroll = db.get(Payroll, adjustment.payroll_id)
                if source_payroll and source_payroll.worker_id == payroll.worker_id:
                    adjustment.status = "APPLIED"
                    audit(db, company_id, user, "payroll.adjustment.applied", "payroll_adjustment", adjustment.id, {"payroll_id": payroll.id})
    period.status = (
        "PAID" if all(payroll.payroll_status == "PAID" for payroll in records)
        else "APPROVED"
    )
    period.approved_by = user.id
    period.approved_at = datetime.now(timezone.utc)
    period.approval_reason = payload.reason
    audit(db, company_id, user, "payroll.period.approved", "payroll_period", period.id, {"reason": payload.reason, "version": period.version})
    db.commit()
    return {"year": year, "month": month, "status": period.status, "approved_by": user.id, "approved_at": period.approved_at, "version": period.version}


@router.post("/payroll/periods/{year}/{month}/lock", tags=["Payroll Processing"])
def lock_payroll_period(
    year: int, month: int, payload: PeriodReasonInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PAYROLL")),
):
    company_id = require_company(user)
    period = db.scalar(select(PayrollPeriod).where(
        PayrollPeriod.company_id == company_id,
        PayrollPeriod.year == year, PayrollPeriod.month == month,
    ))
    if not period:
        raise HTTPException(404, "Payroll period not found")
    if period.status != "PAID":
        raise HTTPException(409, "Only fully paid payroll periods can be locked")
    period.status = "LOCKED"
    period.locked_by = user.id
    period.locked_at = datetime.now(timezone.utc)
    audit(db, company_id, user, "payroll.period.locked", "payroll_period", period.id, {"reason": payload.reason, "version": period.version})
    db.commit()
    return {"year": year, "month": month, "status": period.status, "locked_by": user.id, "locked_at": period.locked_at}


@router.put("/settings/payroll/reopen-permissions/{user_id}", tags=["Settings & Permissions"])
def grant_reopen_permission(
    user_id: str, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN")),
):
    company_id = require_company(user)
    target = db.scalar(select(User).where(
        User.id == user_id, User.company_id == company_id, User.is_active.is_(True)
    ))
    if not target:
        raise HTTPException(404, "Active company user not found")
    grant = db.scalar(select(PayrollPermissionGrant).where(
        PayrollPermissionGrant.company_id == company_id,
        PayrollPermissionGrant.user_id == user_id,
        PayrollPermissionGrant.permission == "PAYROLL_REOPEN",
    ))
    if not grant:
        grant = PayrollPermissionGrant(
            company_id=company_id, user_id=user_id,
            permission="PAYROLL_REOPEN", granted_by=user.id,
        )
        db.add(grant)
        audit(db, company_id, user, "payroll.reopen_permission.granted", "user", user_id)
    db.commit()
    return {"user_id": user_id, "permission": "PAYROLL_REOPEN", "granted": True}


@router.post("/payroll/periods/{year}/{month}/reopen", tags=["Payroll Processing"])
def reopen_payroll_period(
    year: int, month: int, payload: PeriodReasonInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PAYROLL")),
):
    company_id = require_company(user)
    grant = db.scalar(select(PayrollPermissionGrant).where(
        PayrollPermissionGrant.company_id == company_id,
        PayrollPermissionGrant.user_id == user.id,
        PayrollPermissionGrant.permission == "PAYROLL_REOPEN",
    ))
    if not grant:
        raise HTTPException(403, "Payroll reopen permission is required")
    period = db.scalar(select(PayrollPeriod).where(
        PayrollPeriod.company_id == company_id,
        PayrollPeriod.year == year, PayrollPeriod.month == month,
    ))
    if not period or period.status != "LOCKED":
        raise HTTPException(409, "Only locked payroll periods can be reopened")
    period.status = "PAID"
    period.locked_by = None
    period.locked_at = None
    audit(db, company_id, user, "payroll.period.reopened", "payroll_period", period.id, {"reason": payload.reason, "version": period.version})
    db.commit()
    return {"year": year, "month": month, "status": period.status}


@router.post("/payroll/{payroll_id}/adjustments", status_code=201, tags=["Payroll Processing"])
def create_payroll_adjustment(
    payroll_id: str, payload: PayrollAdjustmentInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PAYROLL")),
):
    company_id = require_company(user)
    payroll = db.scalar(select(Payroll).where(
        Payroll.id == payroll_id, Payroll.company_id == company_id
    ))
    if not payroll:
        raise HTTPException(404, "Payroll record not found")
    period = db.scalar(select(PayrollPeriod).where(
        PayrollPeriod.company_id == company_id,
        PayrollPeriod.year == payroll.year, PayrollPeriod.month == payroll.month,
    ))
    if not period or period.status != "LOCKED":
        raise HTTPException(409, "Adjustments are required only for locked payroll periods")
    next_year = payroll.year + (1 if payroll.month == 12 else 0)
    next_month = 1 if payroll.month == 12 else payroll.month + 1
    adjustment = PayrollAdjustment(
        company_id=company_id, payroll_id=payroll.id,
        effective_year=next_year, effective_month=next_month,
        amount_mmk=payload.amount_mmk, reason=payload.reason,
        created_by=user.id,
    )
    db.add(adjustment)
    audit(db, company_id, user, "payroll.adjustment.requested", "payroll_adjustment", adjustment.id, {"reason": payload.reason, "amount_mmk": payload.amount_mmk, "effective_year": next_year, "effective_month": next_month})
    db.commit()
    return {"id": adjustment.id, "status": adjustment.status, "effective_year": next_year, "effective_month": next_month}


@router.post("/payroll-adjustments/{adjustment_id}/review", tags=["Payroll Processing"])
def review_payroll_adjustment(
    adjustment_id: str, payload: ReviewInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PAYROLL")),
):
    company_id = require_company(user)
    adjustment = db.scalar(select(PayrollAdjustment).where(
        PayrollAdjustment.id == adjustment_id,
        PayrollAdjustment.company_id == company_id,
    ))
    if not adjustment:
        raise HTTPException(404, "Payroll adjustment not found")
    if adjustment.status != "PENDING":
        raise HTTPException(409, "Only pending adjustments can be reviewed")
    if adjustment.created_by == user.id:
        raise HTTPException(403, "Adjustment requester cannot approve their own adjustment")
    adjustment.status = payload.status
    adjustment.approved_by = user.id if payload.status == "APPROVED" else None
    audit(db, company_id, user, f"payroll.adjustment.{payload.status.lower()}", "payroll_adjustment", adjustment.id, {"reason": payload.note})
    db.commit()
    return {"id": adjustment.id, "status": adjustment.status}


@router.put("/settings/compliance-rules", tags=["Myanmar Compliance"])
def set_compliance_rule(
    payload: ComplianceRuleInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PAYROLL")),
):
    company_id = require_company(user)
    if payload.effective_to and payload.effective_to < payload.effective_from:
        raise HTTPException(422, "Rule end date cannot precede its effective date")
    rule = ComplianceRule(
        company_id=company_id,
        code=payload.code,
        name=payload.name,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        configuration_json=json.dumps(payload.configuration, sort_keys=True),
        reference_note=payload.reference_note,
        reviewed_by=user.id,
    )
    db.add(rule)
    audit(db, company_id, user, "compliance.rule.configured", "compliance_rule", rule.id, {"code": payload.code, "effective_from": payload.effective_from, "reference_note": payload.reference_note})
    db.commit()
    return {"id": rule.id, "code": rule.code, "effective_from": rule.effective_from, "effective_to": rule.effective_to, "reviewed_by": rule.reviewed_by}


@router.get("/settings/compliance-rules", tags=["Myanmar Compliance"])
def list_compliance_rules(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    company_id = require_company(user)
    rows = db.scalars(select(ComplianceRule).where(
        ComplianceRule.company_id == company_id
    ).order_by(ComplianceRule.code, ComplianceRule.effective_from.desc())).all()
    return [{
        "id": rule.id, "code": rule.code, "name": rule.name,
        "effective_from": rule.effective_from, "effective_to": rule.effective_to,
        "configuration": json.loads(rule.configuration_json),
        "reference_note": rule.reference_note, "reviewed_by": rule.reviewed_by,
    } for rule in rows]


@router.get("/payroll/{payroll_id}/payslip", tags=["Payslips & Payments"])
def payslip(
    payroll_id: str, db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    payroll = db.scalar(select(Payroll).where(
        Payroll.id == payroll_id, Payroll.company_id == company_id
    ))
    if not payroll:
        raise HTTPException(404, "Payroll record not found")
    worker = get_worker(db, company_id, payroll.worker_id)
    require_worker_access(db, company_id, user, payroll.worker_id)
    company = db.get(Company, company_id)
    profile = db.get(EmployeeProfile, worker.id)
    site = db.get(Site, worker.site_id) if worker.site_id else None
    period = db.scalar(select(PayrollPeriod).where(
        PayrollPeriod.company_id == company_id,
        PayrollPeriod.year == payroll.year,
        PayrollPeriod.month == payroll.month,
    ))
    components = db.scalars(select(PayrollComponent).where(
        PayrollComponent.company_id == company_id, PayrollComponent.payroll_id == payroll_id
    )).all()
    payments = db.scalars(select(PayrollPayment).where(
        PayrollPayment.company_id == company_id, PayrollPayment.payroll_id == payroll_id
    ).order_by(PayrollPayment.payment_date)).all()
    paid = sum(p.amount_mmk for p in payments if p.payment_status == "CONFIRMED")
    attendance = db.scalars(select(Attendance).where(
        Attendance.company_id == company_id,
        Attendance.worker_id == worker.id,
        Attendance.work_date.between(
            date(payroll.year, payroll.month, 1),
            date(payroll.year, payroll.month, calendar.monthrange(payroll.year, payroll.month)[1]),
        ),
    )).all()
    leave_records = db.scalars(select(LeaveRequest).where(
        LeaveRequest.company_id == company_id,
        LeaveRequest.worker_id == worker.id,
        LeaveRequest.status == "APPROVED",
        LeaveRequest.start_date <= date(payroll.year, payroll.month, calendar.monthrange(payroll.year, payroll.month)[1]),
        LeaveRequest.end_date >= date(payroll.year, payroll.month, 1),
    )).all()
    return {
        "payroll_id": payroll.id, "employee_code": worker.employee_code,
        "employee_name": worker.full_name, "year": payroll.year, "month": payroll.month,
        "company_name": company.name if company else "",
        "position": profile.position if profile else "Security Guard",
        "site_name": site.name if site else "",
        "status": payroll.payroll_status,
        "period_status": period.status if period else "DRAFT",
        "version": period.version if period else 0,
        "issued_at": datetime.now(timezone.utc),
        "gross_pay_mmk": payroll.base_salary_mmk + payroll.allowance_mmk,
        "deductions_mmk": payroll.deduction_mmk, "net_pay_mmk": payroll.net_salary_mmk,
        "paid_mmk": paid, "outstanding_mmk": max(0, payroll.net_salary_mmk - paid),
        "payment_ready": bool(period and period.status in ("APPROVED", "PAID", "LOCKED")),
        "bank_transfer_automated": False,
        "attendance_summary": {
            "present": sum(a.attendance_status in ("PRESENT", "LATE") for a in attendance),
            "absent": sum(a.attendance_status == "ABSENT" for a in attendance),
            "late": sum(a.attendance_status == "LATE" for a in attendance),
        },
        "leave_summary": [{
            "leave_type": leave.leave_type,
            "start_date": leave.start_date,
            "end_date": leave.end_date,
            "status": leave.status,
        } for leave in leave_records],
        "components": [{"type": c.component_type, "code": c.code, "description": c.description, "amount_mmk": c.amount_mmk} for c in components],
        "payments": [{"date": p.payment_date, "amount_mmk": p.amount_mmk, "method": p.payment_method, "reference": p.reference, "status": p.payment_status} for p in payments],
    }


@router.post("/payroll/{payroll_id}/payments", status_code=201, tags=["Payslips & Payments"])
def record_payment(
    payroll_id: str, payload: PaymentInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PAYROLL")),
):
    company_id = require_company(user)
    payroll = db.scalar(select(Payroll).where(
        Payroll.id == payroll_id, Payroll.company_id == company_id
    ))
    if not payroll:
        raise HTTPException(404, "Payroll record not found")
    if payroll.payroll_status not in ("APPROVED", "PAID"):
        raise HTTPException(409, "Payroll must be approved before recording payment")
    period = db.scalar(select(PayrollPeriod).where(
        PayrollPeriod.company_id == company_id,
        PayrollPeriod.year == payroll.year,
        PayrollPeriod.month == payroll.month,
    ))
    if not period or period.status not in ("APPROVED", "PAID"):
        raise HTTPException(409, "Payroll period is not approved for manual payment confirmation")
    payment_rows = db.scalars(select(PayrollPayment).where(
        PayrollPayment.company_id == company_id, PayrollPayment.payroll_id == payroll_id
    )).all()
    if payload.reference and db.scalar(select(PayrollPayment.id).where(
        PayrollPayment.company_id == company_id,
        PayrollPayment.reference == payload.reference,
    )):
        raise HTTPException(409, "Payment reference has already been recorded")
    paid = sum(
        payment.amount_mmk for payment in payment_rows
        if payment.payment_status == "CONFIRMED"
    )
    if paid + payload.amount_mmk > payroll.net_salary_mmk:
        raise HTTPException(422, "Payment exceeds remaining net salary")
    payment = PayrollPayment(
        company_id=company_id, payroll_id=payroll_id, recorded_by=user.id,
        payment_status="CONFIRMED", **payload.model_dump(),
    )
    db.add(payment)
    db.flush()
    if paid + payload.amount_mmk == payroll.net_salary_mmk:
        payroll.payroll_status = "PAID"
    all_payrolls = db.scalars(select(Payroll).where(
        Payroll.company_id == company_id,
        Payroll.year == period.year, Payroll.month == period.month,
    )).all()
    if all(record.payroll_status == "PAID" for record in all_payrolls):
        period.status = "PAID"
    audit(db, company_id, user, "payroll.payment.recorded", "payroll_payment", payment.id, {"payroll_id": payroll_id, "amount_mmk": payload.amount_mmk})
    db.commit()
    return {
        "id": payment.id,
        "payroll_status": payroll.payroll_status,
        "period_status": period.status,
        "payment_status": "CONFIRMED",
        "bank_transfer_initiated": False,
    }


@router.post("/payroll/{payroll_id}/payment-attempts", status_code=201, tags=["Payslips & Payments"])
def record_payment_attempt(
    payroll_id: str, payload: PaymentAttemptInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PAYROLL")),
):
    company_id = require_company(user)
    payroll = db.scalar(select(Payroll).where(
        Payroll.id == payroll_id, Payroll.company_id == company_id
    ))
    if not payroll:
        raise HTTPException(404, "Payroll record not found")
    period = db.scalar(select(PayrollPeriod).where(
        PayrollPeriod.company_id == company_id,
        PayrollPeriod.year == payroll.year, PayrollPeriod.month == payroll.month,
    ))
    if not period or period.status not in ("APPROVED", "PAID"):
        raise HTTPException(409, "Payroll must be approved before payment attempts")
    existing = db.scalars(select(PayrollPayment).where(
        PayrollPayment.company_id == company_id,
        PayrollPayment.payroll_id == payroll_id,
    )).all()
    if payload.reference and db.scalar(select(PayrollPayment.id).where(
        PayrollPayment.company_id == company_id,
        PayrollPayment.reference == payload.reference,
    )):
        raise HTTPException(409, "Payment reference has already been recorded")
    payment = PayrollPayment(
        company_id=company_id, payroll_id=payroll_id, recorded_by=user.id,
        payment_status=payload.payment_status, **payload.model_dump(exclude={"payment_status"}),
    )
    db.add(payment)
    audit(db, company_id, user, "payroll.payment.attempt_recorded", "payroll_payment", payment.id, {"status": payload.payment_status, "bank_transfer_initiated": False})
    db.commit()
    return {
        "id": payment.id, "payment_status": payment.payment_status,
        "bank_transfer_initiated": False,
        "message": "Attempt recorded for reconciliation; no bank or wallet transfer was initiated.",
    }


@router.post("/payroll/{payroll_id}/payments/{payment_id}/retry", tags=["Payslips & Payments"])
def retry_failed_payment(
    payroll_id: str, payment_id: str, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PAYROLL")),
):
    company_id = require_company(user)
    payment = db.scalar(select(PayrollPayment).where(
        PayrollPayment.id == payment_id,
        PayrollPayment.payroll_id == payroll_id,
        PayrollPayment.company_id == company_id,
    ))
    if not payment:
        raise HTTPException(404, "Payment attempt not found")
    if payment.payment_status != "FAILED":
        raise HTTPException(409, "Only failed attempts can be retried")
    payment.payment_status = "PENDING"
    audit(db, company_id, user, "payroll.payment.retry_queued", "payroll_payment", payment.id, {"bank_transfer_initiated": False})
    db.commit()
    return {
        "id": payment.id, "payment_status": payment.payment_status,
        "bank_transfer_initiated": False,
    }


@router.put("/payroll/{payroll_id}/payments/{payment_id}/confirm", tags=["Payslips & Payments"])
def confirm_payment_attempt(
    payroll_id: str, payment_id: str, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PAYROLL")),
):
    company_id = require_company(user)
    payroll = db.scalar(select(Payroll).where(
        Payroll.id == payroll_id, Payroll.company_id == company_id
    ))
    payment = db.scalar(select(PayrollPayment).where(
        PayrollPayment.id == payment_id,
        PayrollPayment.payroll_id == payroll_id,
        PayrollPayment.company_id == company_id,
    ))
    if not payroll or not payment:
        raise HTTPException(404, "Payroll or payment attempt not found")
    if payment.payment_status != "PENDING":
        raise HTTPException(409, "Only pending payment attempts can be confirmed")
    if payment.reference:
        duplicate = db.scalar(select(PayrollPayment.id).where(
            PayrollPayment.company_id == company_id,
            PayrollPayment.reference == payment.reference,
            PayrollPayment.payment_status == "CONFIRMED",
        ))
        if duplicate:
            raise HTTPException(409, "Payment reference has already been confirmed")
    confirmed = db.scalars(select(PayrollPayment).where(
        PayrollPayment.company_id == company_id,
        PayrollPayment.payroll_id == payroll_id,
        PayrollPayment.payment_status == "CONFIRMED",
    )).all()
    if sum(row.amount_mmk for row in confirmed) + payment.amount_mmk > payroll.net_salary_mmk:
        raise HTTPException(422, "Confirmation would exceed the remaining net salary")
    payment.payment_status = "CONFIRMED"
    total_paid = sum(row.amount_mmk for row in confirmed) + payment.amount_mmk
    if total_paid == payroll.net_salary_mmk:
        payroll.payroll_status = "PAID"
    period = db.scalar(select(PayrollPeriod).where(
        PayrollPeriod.company_id == company_id,
        PayrollPeriod.year == payroll.year,
        PayrollPeriod.month == payroll.month,
    ))
    if period:
        payrolls = db.scalars(select(Payroll).where(
            Payroll.company_id == company_id,
            Payroll.year == period.year,
            Payroll.month == period.month,
        )).all()
        if all(row.payroll_status == "PAID" for row in payrolls):
            period.status = "PAID"
    audit(db, company_id, user, "payroll.payment.confirmed", "payroll_payment", payment.id, {"bank_transfer_initiated": False, "amount_mmk": payment.amount_mmk})
    db.commit()
    return {
        "id": payment.id, "payment_status": payment.payment_status,
        "payroll_status": payroll.payroll_status,
        "bank_transfer_initiated": False,
    }


@router.post("/loans-advances", status_code=201, tags=["Loans & Advances"])
def request_loan(
    payload: LoanInput, db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    get_worker(db, company_id, payload.worker_id)
    require_worker_access(db, company_id, user, payload.worker_id)
    loan = LoanAdvance(
        company_id=company_id, outstanding_mmk=payload.principal_mmk,
        **payload.model_dump(),
    )
    db.add(loan)
    audit(db, company_id, user, "loan.requested", "loan_advance", loan.id)
    db.commit()
    return {"id": loan.id, "status": loan.status}


@router.get("/loans-advances", tags=["Loans & Advances"])
def list_loans(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    company_id = require_company(user)
    rows = db.scalars(select(LoanAdvance).where(
        LoanAdvance.company_id == company_id
    ).order_by(LoanAdvance.created_at.desc()).limit(200)).all()
    if user.role == "GUARD":
        profile = db.scalar(select(EmployeeProfile).where(
            EmployeeProfile.user_id == user.id
        ))
        rows = [row for row in rows if profile and row.worker_id == profile.worker_id]
    return [{"id": x.id, "worker_id": x.worker_id, "kind": x.kind, "principal_mmk": x.principal_mmk, "outstanding_mmk": x.outstanding_mmk, "monthly_repayment_mmk": x.monthly_repayment_mmk, "status": x.status} for x in rows]


@router.post("/loans-advances/{loan_id}/review", tags=["Loans & Advances"])
def review_loan(
    loan_id: str, payload: ReviewInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PAYROLL")),
):
    company_id = require_company(user)
    loan = db.scalar(select(LoanAdvance).where(
        LoanAdvance.id == loan_id, LoanAdvance.company_id == company_id
    ))
    if not loan:
        raise HTTPException(404, "Loan or advance not found")
    if loan.status != "PENDING":
        raise HTTPException(409, "Only pending requests can be reviewed")
    loan.status = payload.status
    loan.approved_by = user.id if payload.status == "APPROVED" else None
    audit(db, company_id, user, f"loan.{payload.status.lower()}", "loan_advance", loan.id, {"note": payload.note})
    db.commit()
    return {"id": loan.id, "status": loan.status}


@router.post("/expense-claims", status_code=201, tags=["Expense Claims"])
def create_claim(
    payload: ClaimInput, db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    get_worker(db, company_id, payload.worker_id)
    require_worker_access(db, company_id, user, payload.worker_id)
    claim = ExpenseClaim(company_id=company_id, **payload.model_dump())
    db.add(claim)
    audit(db, company_id, user, "claim.submitted", "expense_claim", claim.id)
    db.commit()
    return {"id": claim.id, "status": claim.status}


@router.get("/expense-claims", tags=["Expense Claims"])
def list_claims(
    status_filter: Optional[Literal["PENDING", "APPROVED", "REJECTED"]] = None,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    query = select(ExpenseClaim).where(ExpenseClaim.company_id == company_id)
    if status_filter:
        query = query.where(ExpenseClaim.status == status_filter)
    rows = db.scalars(query.order_by(ExpenseClaim.claim_date.desc()).limit(200)).all()
    if user.role == "GUARD":
        profile = db.scalar(select(EmployeeProfile).where(
            EmployeeProfile.user_id == user.id
        ))
        rows = [row for row in rows if profile and row.worker_id == profile.worker_id]
    return [{"id": c.id, "worker_id": c.worker_id, "claim_date": c.claim_date, "category": c.category, "amount_mmk": c.amount_mmk, "evidence_url": c.evidence_url, "status": c.status} for c in rows]


@router.post("/expense-claims/{claim_id}/review", tags=["Expense Claims"])
def review_claim(
    claim_id: str, payload: ReviewInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PAYROLL")),
):
    company_id = require_company(user)
    claim = db.scalar(select(ExpenseClaim).where(
        ExpenseClaim.id == claim_id, ExpenseClaim.company_id == company_id
    ))
    if not claim:
        raise HTTPException(404, "Expense claim not found")
    if claim.status != "PENDING":
        raise HTTPException(409, "Only pending claims can be reviewed")
    claim.status = payload.status
    claim.reviewed_by = user.id
    audit(db, company_id, user, f"claim.{payload.status.lower()}", "expense_claim", claim.id, {"note": payload.note})
    db.commit()
    return {"id": claim.id, "status": claim.status}


@router.post("/site-contracts", status_code=201, tags=["Site Contracts"])
def create_contract(
    payload: ContractInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "MANAGER")),
):
    company_id = require_company(user)
    get_site(db, company_id, payload.site_id)
    if payload.end_date and payload.end_date < payload.start_date:
        raise HTTPException(422, "Contract end date cannot precede start date")
    contract = SiteContract(company_id=company_id, **payload.model_dump())
    db.add(contract)
    audit(db, company_id, user, "site_contract.created", "site_contract", contract.id)
    db.commit()
    return {"id": contract.id, **payload.model_dump(mode="json"), "is_active": contract.is_active}


@router.get("/site-contracts", tags=["Site Contracts"])
def list_contracts(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    company_id = require_company(user)
    rows = db.scalars(select(SiteContract).where(
        SiteContract.company_id == company_id
    ).order_by(SiteContract.start_date.desc()).limit(200)).all()
    return [{"id": c.id, "site_id": c.site_id, "customer_name": c.customer_name, "start_date": c.start_date, "end_date": c.end_date, "required_guards": c.required_guards, "billing_rate_mmk": c.billing_rate_mmk, "guard_rate_basis": c.guard_rate_basis, "is_active": c.is_active} for c in rows]


@router.put("/settings/payroll", tags=["Settings & Permissions"])
def set_policy(
    payload: PolicyInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "SUPERADMIN")),
):
    company_id = require_company(user)
    if payload.key in ("working_days_per_month", "hours_per_day", "overtime_multiplier", "late_deduction_per_minute", "deduction_cap_mmk", "night_shift_allowance_mmk"):
        try:
            number = float(payload.value)
        except ValueError:
            raise HTTPException(422, "Numeric payroll policy requires a numeric value")
        if number < 0:
            raise HTTPException(422, "Policy values cannot be negative")
        if payload.key in (
            "working_days_per_month", "deduction_cap_mmk",
            "night_shift_allowance_mmk",
        ) and not number.is_integer():
            raise HTTPException(422, "This policy value must be a whole number")
    if payload.key.endswith("_enabled") and payload.value.lower() not in ("true", "false"):
        raise HTTPException(422, "Permission switches must be true or false")
    policy = db.scalar(select(CompanyPolicy).where(
        CompanyPolicy.company_id == company_id, CompanyPolicy.key == payload.key
    ))
    if not policy:
        policy = CompanyPolicy(company_id=company_id, key=payload.key, updated_by=user.id, value=payload.value)
        db.add(policy)
    else:
        policy.value = payload.value
        policy.updated_by = user.id
        policy.updated_at = datetime.now(timezone.utc)
    audit(db, company_id, user, "policy.updated", "company_policy", policy.id, {"key": payload.key})
    db.commit()
    return {"key": policy.key, "value": policy.value}


@router.get("/settings/payroll", tags=["Settings & Permissions"])
def get_policies(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    company_id = require_company(user)
    rows = db.scalars(select(CompanyPolicy).where(
        CompanyPolicy.company_id == company_id
    ).order_by(CompanyPolicy.key)).all()
    return [{"key": r.key, "value": r.value} for r in rows]


@router.get("/reports/payroll-summary", tags=["Reports & Analytics"])
def payroll_summary(
    year: int = Query(ge=2020, le=2100), month: int = Query(ge=1, le=12),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    records = db.scalars(select(Payroll).where(
        Payroll.company_id == company_id, Payroll.year == year, Payroll.month == month
    )).all()
    return {
        "year": year, "month": month, "employee_count": len(records),
        "gross_pay_mmk": sum(r.base_salary_mmk + r.allowance_mmk for r in records),
        "deductions_mmk": sum(r.deduction_mmk for r in records),
        "net_pay_mmk": sum(r.net_salary_mmk for r in records),
        "by_status": {
            status: sum(r.net_salary_mmk for r in records if r.payroll_status == status)
            for status in ("DRAFT", "APPROVED", "PAID")
        },
    }


@router.get("/reports/site-costs", tags=["Reports & Analytics"])
def site_costs(
    year: int = Query(ge=2020, le=2100), month: int = Query(ge=1, le=12),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    sites = db.scalars(select(Site).where(Site.company_id == company_id)).all()
    rows = []
    for site in sites:
        worker_ids = db.scalars(select(Worker.id).where(
            Worker.company_id == company_id, Worker.site_id == site.id
        )).all()
        payrolls = db.scalars(select(Payroll).where(
            Payroll.company_id == company_id, Payroll.worker_id.in_(worker_ids or [""]),
            Payroll.year == year, Payroll.month == month,
        )).all()
        contracts = db.scalars(select(SiteContract).where(
            SiteContract.company_id == company_id, SiteContract.site_id == site.id,
            SiteContract.start_date <= end,
        )).all()
        revenue = sum(c.billing_rate_mmk * c.required_guards for c in contracts if not c.end_date or c.end_date >= start)
        cost = sum(p.net_salary_mmk for p in payrolls)
        rows.append({"site_id": site.id, "site_name": site.name, "payroll_cost_mmk": cost, "contract_revenue_estimate_mmk": revenue, "estimated_margin_mmk": revenue - cost})
    return rows


@router.get("/reports/staffing", tags=["Reports & Analytics"])
def staffing_report(
    work_date: date, db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    contracts = db.scalars(select(SiteContract).where(
        SiteContract.company_id == company_id,
        SiteContract.is_active.is_(True),
        SiteContract.start_date <= work_date,
    )).all()
    rows = []
    for contract in contracts:
        if contract.end_date and contract.end_date < work_date:
            continue
        assigned_ids = db.scalars(select(RosterAssignment.worker_id).where(
            RosterAssignment.company_id == company_id,
            RosterAssignment.site_id == contract.site_id,
            RosterAssignment.shift_date == work_date,
            RosterAssignment.status.in_(("SCHEDULED", "SWAPPED")),
        )).all()
        present_ids = db.scalars(select(Attendance.worker_id).where(
            Attendance.company_id == company_id,
            Attendance.site_id == contract.site_id,
            Attendance.work_date == work_date,
            Attendance.attendance_status.in_(("PRESENT", "LATE")),
        )).all()
        scheduled_count = len(set(assigned_ids))
        rows.append({
            "contract_id": contract.id,
            "site_id": contract.site_id,
            "customer_name": contract.customer_name,
            "required_guards": contract.required_guards,
            "scheduled_guards": scheduled_count,
            "roster_gap": max(0, contract.required_guards - scheduled_count),
            "present_guards": len(set(present_ids)),
            "attendance_gap": max(0, contract.required_guards - len(set(present_ids))),
        })
    return {"work_date": work_date, "sites": rows}


@router.get("/reports/payroll-export", tags=["Reports & Analytics"])
def export_payroll(
    year: int = Query(ge=2020, le=2100),
    month: int = Query(ge=1, le=12),
    file_format: Literal["csv", "xlsx"] = Query(default="csv", alias="format"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PAYROLL")),
):
    company_id = require_company(user)
    records = db.scalars(select(Payroll).where(
        Payroll.company_id == company_id,
        Payroll.year == year,
        Payroll.month == month,
        Payroll.payroll_status.in_(("APPROVED", "PAID")),
    ).order_by(Payroll.worker_id)).all()
    headers = [
        "employee_code", "employee_name", "year", "month", "gross_pay_mmk",
        "deductions_mmk", "net_pay_mmk", "status",
    ]
    output_rows = []
    for payroll in records:
        worker = get_worker(db, company_id, payroll.worker_id)
        output_rows.append([
            worker.employee_code, worker.full_name, payroll.year, payroll.month,
            payroll.base_salary_mmk + payroll.allowance_mmk,
            payroll.deduction_mmk, payroll.net_salary_mmk, payroll.payroll_status,
        ])
    filename = f"payroll-{year}-{month:02d}.{file_format}"
    if file_format == "csv":
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(output_rows)
        content = io.BytesIO(stream.getvalue().encode("utf-8-sig"))
        media_type = "text/csv; charset=utf-8"
    else:
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Payroll"
        sheet.append(headers)
        for row in output_rows:
            sheet.append(row)
        content = io.BytesIO()
        workbook.save(content)
        content.seek(0)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return StreamingResponse(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/audit", tags=["Audit & Compliance"])
def list_audit(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "SUPERADMIN", "AUDITOR")),
):
    query = select(AuditRecord)
    if user.role != "SUPERADMIN":
        company_id = require_company(user)
        query = query.where(AuditRecord.company_id == company_id)
    rows = db.scalars(
        query.order_by(AuditRecord.created_at.desc())
        .offset(offset).limit(limit)
    ).all()
    return [{"id": r.id, "actor_id": r.actor_id, "action": r.action, "entity_type": r.entity_type, "entity_id": r.entity_id, "details": json.loads(r.details_json), "created_at": r.created_at} for r in rows]
