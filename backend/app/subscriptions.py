import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.main import Base, Company, User, Worker, Site, get_current_user, get_db, require_company, require_roles
from app.operations import audit


router = APIRouter(prefix="/api/v1", tags=["SaaS Billing & Support"])


def new_id() -> str:
    return str(uuid.uuid4())


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    monthly_company_fee_mmk: Mapped[int] = mapped_column(Integer, default=0)
    monthly_employee_fee_mmk: Mapped[int] = mapped_column(Integer, default=0)
    employee_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    site_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    features_json: Mapped[str] = mapped_column(Text, default="[]")
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class CompanySubscription(Base):
    __tablename__ = "company_subscriptions"
    __table_args__ = (UniqueConstraint("company_id", name="uq_subscription_company"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("subscription_plans.id"))
    pending_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("subscription_plans.id"), nullable=True
    )
    pending_billing_cycle: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="TRIAL", index=True)
    billing_cycle: Mapped[str] = mapped_column(String(20), default="MONTHLY")
    starts_on: Mapped[date] = mapped_column(Date)
    current_period_end: Mapped[date] = mapped_column(Date)
    trial_ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    pending_effective_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class SubscriptionHistory(Base):
    __tablename__ = "subscription_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("company_subscriptions.id"), index=True
    )
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(50), index=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )


class BillingInvoice(Base):
    __tablename__ = "billing_invoices"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "service_start", "service_end",
            name="uq_invoice_subscription_service_period",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("company_subscriptions.id"), index=True
    )
    plan_id: Mapped[str] = mapped_column(ForeignKey("subscription_plans.id"))
    invoice_number: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    plan_name: Mapped[str] = mapped_column(String(120))
    service_start: Mapped[date] = mapped_column(Date)
    service_end: Mapped[date] = mapped_column(Date)
    employee_count: Mapped[int] = mapped_column(Integer)
    amount_mmk: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="ISSUED", index=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    due_on: Mapped[date] = mapped_column(Date)
    receipt_reference: Mapped[str] = mapped_column(String(160), default="")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )


class UsageSnapshot(Base):
    __tablename__ = "subscription_usage"
    __table_args__ = (
        UniqueConstraint("company_id", "period_start", "metric", name="uq_usage_company_period_metric"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date, index=True)
    metric: Mapped[str] = mapped_column(String(40))
    quantity: Mapped[int] = mapped_column(Integer)
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    subject: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="NORMAL")
    staff_response: Mapped[str] = mapped_column(Text, default="")
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AccountClosureRequest(Base):
    __tablename__ = "account_closure_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reason: Mapped[str] = mapped_column(String(1000))
    review_note: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InputModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class PlanInput(InputModel):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=500)
    monthly_company_fee_mmk: int = Field(default=0, ge=0)
    monthly_employee_fee_mmk: int = Field(default=0, ge=0)
    employee_limit: int | None = Field(default=None, ge=1)
    site_limit: int | None = Field(default=None, ge=1)
    features: list[str] = Field(default_factory=list, max_length=100)
    is_active: bool = True


class StartTrialInput(InputModel):
    plan_id: str
    billing_cycle: Literal["MONTHLY", "ANNUAL"] = "MONTHLY"


class PlanChangeInput(InputModel):
    plan_id: str
    billing_cycle: Literal["MONTHLY", "ANNUAL"] | None = None


class SubscriptionStatusInput(InputModel):
    status: Literal["TRIAL", "ACTIVE", "SUSPENDED", "EXPIRED"]
    valid_through: date | None = None
    reason: str = Field(min_length=3, max_length=500)


class ReceiptInput(InputModel):
    reference: str = Field(min_length=3, max_length=160)


class TicketInput(InputModel):
    subject: str = Field(min_length=3, max_length=160)
    message: str = Field(min_length=5, max_length=5000)
    priority: str = Field(default="NORMAL", pattern=r"^(LOW|NORMAL|HIGH)$")


class TicketReviewInput(InputModel):
    status: str = Field(pattern=r"^(OPEN|IN_PROGRESS|RESOLVED|CLOSED)$")
    response: str = Field(default="", max_length=5000)


class ClosureInput(InputModel):
    reason: str = Field(min_length=10, max_length=1000)


class ClosureReviewInput(InputModel):
    status: str = Field(pattern=r"^(APPROVED|REJECTED)$")
    note: str = Field(min_length=3, max_length=1000)


def plan_features(plan: SubscriptionPlan) -> list[str]:
    try:
        features = json.loads(plan.features_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(500, "Subscription plan features are invalid") from exc
    if not isinstance(features, list) or any(not isinstance(item, str) for item in features):
        raise HTTPException(500, "Subscription plan features are invalid")
    return features


def effective_status(subscription: CompanySubscription) -> str:
    today = date.today()
    if subscription.status == "TRIAL" and subscription.trial_ends_on and subscription.trial_ends_on < today:
        return "EXPIRED"
    if subscription.status == "ACTIVE" and subscription.current_period_end < today:
        return "EXPIRED"
    return subscription.status


def enforce_company_subscription_status(
    db: Session, user: User, request_path: str
) -> None:
    if not user.company_id:
        return
    if (
        request_path.startswith("/api/v1/billing/")
        or request_path.startswith("/api/v1/support/")
        or request_path == "/api/v1/auth/me"
    ):
        return
    subscription = db.scalar(select(CompanySubscription).where(
        CompanySubscription.company_id == user.company_id
    ))
    if subscription and effective_status(subscription) not in ("TRIAL", "ACTIVE"):
        raise HTTPException(
            402,
            "Company subscription is not active; billing and support remain available",
        )


def assert_subscription_access(
    db: Session,
    company_id: str,
    *,
    feature: str | None = None,
    employee_increment: int = 0,
    site_increment: int = 0,
) -> None:
    subscription = db.scalar(
        select(CompanySubscription).where(CompanySubscription.company_id == company_id)
    )
    if not subscription:
        return
    status = effective_status(subscription)
    if status not in ("TRIAL", "ACTIVE"):
        raise HTTPException(402, f"Company subscription is {status.lower()}")
    plan = db.get(SubscriptionPlan, subscription.plan_id)
    if not plan or not plan.is_active:
        raise HTTPException(402, "The subscribed plan is unavailable")
    if feature and "*" not in plan_features(plan) and feature not in plan_features(plan):
        raise HTTPException(403, f"Your subscription does not include the {feature} feature")
    if employee_increment and plan.employee_limit is not None:
        current = len(db.scalars(select(Worker.id).where(
            Worker.company_id == company_id, Worker.is_active.is_(True)
        )).all())
        if current + employee_increment > plan.employee_limit:
            raise HTTPException(409, "Employee limit for this subscription plan has been reached")
    if site_increment and plan.site_limit is not None:
        current_sites = len(db.scalars(select(Site.id).where(
            Site.company_id == company_id, Site.is_active.is_(True)
        )).all())
        if current_sites + site_increment > plan.site_limit:
            raise HTTPException(409, "Site limit for this subscription plan has been reached")


def subscription_summary(db: Session, company_id: str) -> dict:
    subscription = db.scalar(
        select(CompanySubscription).where(CompanySubscription.company_id == company_id)
    )
    if not subscription:
        return {"status": "NOT_CONFIGURED", "licensed": True, "features": ["*"]}
    plan = db.get(SubscriptionPlan, subscription.plan_id)
    current_status = effective_status(subscription)
    if not plan:
        raise HTTPException(500, "Subscription plan was not found")
    return {
        "status": current_status,
        "licensed": current_status in ("TRIAL", "ACTIVE"),
        "plan": {"id": plan.id, "code": plan.code, "name": plan.name},
        "features": plan_features(plan),
        "employee_limit": plan.employee_limit,
        "site_limit": plan.site_limit,
        "billing_cycle": subscription.billing_cycle,
        "period_end": subscription.current_period_end,
        "trial_ends_on": subscription.trial_ends_on,
        "pending_plan_id": subscription.pending_plan_id,
        "pending_billing_cycle": subscription.pending_billing_cycle,
        "pending_effective_on": subscription.pending_effective_on,
    }

def _history(
    db: Session, subscription: CompanySubscription, actor: User,
    action: str, details: dict,
) -> None:
    db.add(SubscriptionHistory(
        company_id=subscription.company_id,
        subscription_id=subscription.id,
        actor_id=actor.id,
        action=action,
        details_json=json.dumps(details, default=str),
    ))


@router.get("/billing/plans")
def list_plans(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    plans = db.scalars(
        select(SubscriptionPlan).where(SubscriptionPlan.is_active.is_(True))
        .order_by(SubscriptionPlan.monthly_company_fee_mmk, SubscriptionPlan.name)
    ).all()
    return [{
        "id": item.id, "code": item.code, "name": item.name,
        "description": item.description,
        "monthly_company_fee_mmk": item.monthly_company_fee_mmk,
        "monthly_employee_fee_mmk": item.monthly_employee_fee_mmk,
        "employee_limit": item.employee_limit, "site_limit": item.site_limit,
        "features": plan_features(item),
    } for item in plans]


@router.post("/billing/plans", status_code=201)
def create_plan(
    payload: PlanInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("SUPERADMIN")),
):
    code = payload.code.upper()
    if db.scalar(select(SubscriptionPlan.id).where(SubscriptionPlan.code == code)):
        raise HTTPException(409, "Subscription plan code already exists")
    data = payload.model_dump()
    data.pop("features")
    data["code"] = code
    plan = SubscriptionPlan(
        **data,
        features_json=json.dumps(sorted(set(payload.features))),
    )
    db.add(plan)
    db.commit()
    return {"id": plan.id, "code": plan.code, "name": plan.name}


@router.put("/billing/plans/{plan_id}")
def update_plan(
    plan_id: str, payload: PlanInput, db: Session = Depends(get_db),
    _: User = Depends(require_roles("SUPERADMIN")),
):
    plan = db.get(SubscriptionPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Subscription plan not found")
    code = payload.code.upper()
    duplicate = db.scalar(select(SubscriptionPlan.id).where(
        SubscriptionPlan.code == code, SubscriptionPlan.id != plan_id
    ))
    if duplicate:
        raise HTTPException(409, "Subscription plan code already exists")
    for key, value in payload.model_dump(exclude={"features"}).items():
        setattr(plan, key, value)
    plan.code = code
    plan.features_json = json.dumps(sorted(set(payload.features)))
    db.commit()
    return {"id": plan.id, "code": plan.code, "name": plan.name}


@router.post("/billing/trial", status_code=201)
def start_trial(
    payload: StartTrialInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN")),
):
    company_id = require_company(user)
    if db.scalar(select(CompanySubscription.id).where(
        CompanySubscription.company_id == company_id
    )):
        raise HTTPException(409, "A subscription is already configured for this company")
    plan = db.get(SubscriptionPlan, payload.plan_id)
    if not plan or not plan.is_active:
        raise HTTPException(404, "Active subscription plan not found")
    today = date.today()
    end = today + timedelta(days=14)
    subscription = CompanySubscription(
        company_id=company_id, plan_id=plan.id, status="TRIAL",
        billing_cycle=payload.billing_cycle, starts_on=today,
        current_period_end=end, trial_ends_on=end,
    )
    db.add(subscription)
    db.flush()
    _history(db, subscription, user, "TRIAL_STARTED", {
        "plan_id": plan.id, "trial_ends_on": end,
    })
    audit(db, company_id, user, "subscription.trial_started", "company_subscription", subscription.id, {
        "plan_id": plan.id, "trial_ends_on": end,
    })
    db.commit()
    return subscription_summary(db, company_id)


@router.get("/billing/subscription")
def current_subscription(
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    return subscription_summary(db, company_id)


@router.get("/billing/license")
def validate_license(
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    summary = subscription_summary(db, company_id)
    return {"valid": summary["licensed"], **summary}


@router.post("/billing/subscription/change")
def request_plan_change(
    payload: PlanChangeInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN")),
):
    company_id = require_company(user)
    subscription = db.scalar(select(CompanySubscription).where(
        CompanySubscription.company_id == company_id
    ))
    if not subscription:
        raise HTTPException(404, "Start a trial before changing subscription plans")
    if effective_status(subscription) not in ("TRIAL", "ACTIVE"):
        raise HTTPException(402, "An expired or suspended subscription cannot be changed")
    target = db.get(SubscriptionPlan, payload.plan_id)
    if not target or not target.is_active:
        raise HTTPException(404, "Active subscription plan not found")
    selected_cycle = payload.billing_cycle or subscription.billing_cycle
    if target.id == subscription.plan_id and selected_cycle == subscription.billing_cycle:
        raise HTTPException(409, "This plan is already active")
    effective_on = max(subscription.current_period_end + timedelta(days=1), date.today())
    old_plan_id = subscription.plan_id
    subscription.pending_plan_id = target.id
    subscription.pending_effective_on = effective_on
    subscription.pending_billing_cycle = selected_cycle
    _history(db, subscription, user, "PLAN_CHANGE_SCHEDULED", {
        "from_plan_id": old_plan_id, "to_plan_id": target.id,
        "effective_on": effective_on, "billing_cycle": selected_cycle,
    })
    audit(db, company_id, user, "subscription.plan_change_scheduled", "company_subscription", subscription.id, {
        "from_plan_id": old_plan_id, "to_plan_id": target.id,
        "effective_on": effective_on, "billing_cycle": selected_cycle,
    })
    db.commit()
    return {
        "status": "SCHEDULED", "plan_id": target.id,
        "billing_cycle": selected_cycle, "effective_on": effective_on,
    }


@router.get("/billing/history")
def subscription_history(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    records = db.scalars(select(SubscriptionHistory).where(
        SubscriptionHistory.company_id == company_id
    ).order_by(SubscriptionHistory.created_at.desc()).limit(limit)).all()
    return [{
        "id": row.id, "action": row.action,
        "details": json.loads(row.details_json),
        "created_at": row.created_at,
    } for row in records]


@router.post("/billing/invoices", status_code=201)
def issue_invoice(
    db: Session = Depends(get_db), user: User = Depends(require_roles("ADMIN")),
):
    company_id = require_company(user)
    subscription = db.scalar(select(CompanySubscription).where(
        CompanySubscription.company_id == company_id
    ))
    if not subscription:
        raise HTTPException(404, "No subscription is configured")
    pending_invoice = db.scalar(select(BillingInvoice.id).where(
        BillingInvoice.subscription_id == subscription.id,
        BillingInvoice.status.in_(("ISSUED", "PENDING_REVIEW")),
    ))
    if pending_invoice:
        raise HTTPException(409, "Reconcile or void the outstanding invoice before issuing another")
    start = max(subscription.current_period_end + timedelta(days=1), date.today())
    plan_id = subscription.plan_id
    billing_cycle = subscription.billing_cycle
    if subscription.pending_effective_on and subscription.pending_effective_on <= start:
        plan_id = subscription.pending_plan_id or plan_id
        billing_cycle = subscription.pending_billing_cycle or billing_cycle
    plan = db.get(SubscriptionPlan, plan_id)
    if not plan:
        raise HTTPException(500, "Subscription plan was not found")
    if billing_cycle == "ANNUAL":
        end = start + timedelta(days=364)
        months = 12
    else:
        end = start + timedelta(days=30)
        months = 1
    duplicate = db.scalar(select(BillingInvoice.id).where(
        BillingInvoice.subscription_id == subscription.id,
        BillingInvoice.service_start == start,
        BillingInvoice.service_end == end,
    ))
    if duplicate:
        raise HTTPException(409, "An invoice already exists for this service period")
    employee_count = len(db.scalars(select(Worker.id).where(
        Worker.company_id == company_id, Worker.is_active.is_(True)
    )).all())
    amount = months * (
        plan.monthly_company_fee_mmk
        + plan.monthly_employee_fee_mmk * employee_count
    )
    invoice = BillingInvoice(
        company_id=company_id, subscription_id=subscription.id,
        plan_id=plan.id,
        invoice_number=f"INV-{uuid.uuid4().hex[:12].upper()}",
        plan_name=plan.name, service_start=start, service_end=end,
        employee_count=employee_count, amount_mmk=amount,
        status="ISSUED", due_on=start,
    )
    db.add(invoice)
    db.flush()
    _history(db, subscription, user, "INVOICE_ISSUED", {
        "invoice_id": invoice.id, "amount_mmk": amount,
    })
    audit(db, company_id, user, "subscription.invoice_issued", "billing_invoice", invoice.id, {
        "amount_mmk": amount, "employee_count": employee_count,
    })
    db.commit()
    return _invoice_data(invoice)


def _invoice_data(invoice: BillingInvoice) -> dict:
    return {
        "id": invoice.id, "invoice_number": invoice.invoice_number,
        "plan_id": invoice.plan_id, "plan_name": invoice.plan_name, "service_start": invoice.service_start,
        "service_end": invoice.service_end, "employee_count": invoice.employee_count,
        "amount_mmk": invoice.amount_mmk, "status": invoice.status,
        "issued_at": invoice.issued_at, "due_on": invoice.due_on,
        "receipt_reference": invoice.receipt_reference, "paid_at": invoice.paid_at,
    }


@router.get("/billing/invoices")
def list_invoices(
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    records = db.scalars(select(BillingInvoice).where(
        BillingInvoice.company_id == require_company(user)
    ).order_by(BillingInvoice.issued_at.desc()).limit(500)).all()
    return [_invoice_data(row) for row in records]


@router.post("/billing/invoices/{invoice_id}/payment-receipt")
def submit_receipt(
    invoice_id: str, payload: ReceiptInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN")),
):
    company_id = require_company(user)
    invoice = db.scalar(select(BillingInvoice).where(
        BillingInvoice.id == invoice_id, BillingInvoice.company_id == company_id
    ))
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    if invoice.status == "PAID":
        raise HTTPException(409, "Invoice is already paid")
    if invoice.status == "VOID":
        raise HTTPException(409, "Voided invoices cannot accept receipts")
    invoice.status = "PENDING_REVIEW"
    invoice.receipt_reference = payload.reference
    audit(db, company_id, user, "subscription.receipt_submitted", "billing_invoice", invoice.id)
    db.commit()
    return {"invoice_id": invoice.id, "status": invoice.status, "payment_initiated": False}


@router.put("/billing/invoices/{invoice_id}/confirm")
def confirm_invoice_payment(
    invoice_id: str, db: Session = Depends(get_db),
    user: User = Depends(require_roles("SUPERADMIN")),
):
    invoice = db.get(BillingInvoice, invoice_id)
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    if invoice.status != "PENDING_REVIEW":
        raise HTTPException(409, "Only submitted receipts can be reconciled")
    subscription = db.get(CompanySubscription, invoice.subscription_id)
    if not subscription:
        raise HTTPException(409, "Invoice subscription no longer exists")
    invoice.status = "PAID"
    invoice.paid_at = datetime.now(timezone.utc)
    invoice.confirmed_by = user.id
    subscription.status = "ACTIVE"
    subscription.plan_id = invoice.plan_id
    subscription.billing_cycle = "ANNUAL" if (
        invoice.service_end - invoice.service_start
    ).days > 31 else "MONTHLY"
    subscription.starts_on = invoice.service_start
    subscription.current_period_end = invoice.service_end
    subscription.trial_ends_on = None
    subscription.pending_plan_id = None
    subscription.pending_effective_on = None
    subscription.pending_billing_cycle = None
    company = db.get(Company, invoice.company_id)
    if company:
        company.is_active = True
    _history(db, subscription, user, "PAYMENT_CONFIRMED", {
        "invoice_id": invoice.id, "amount_mmk": invoice.amount_mmk,
        "reference": invoice.receipt_reference,
    })
    audit(db, invoice.company_id, user, "subscription.payment_confirmed", "billing_invoice", invoice.id, {
        "amount_mmk": invoice.amount_mmk,
        "payment_provider_initiated": False,
    })
    db.commit()
    return {"invoice_id": invoice.id, "status": invoice.status, "payment_provider_initiated": False}


@router.get("/billing/renewals/due")
def renewal_reminders(
    days: int = Query(default=14, ge=1, le=90),
    db: Session = Depends(get_db), _: User = Depends(require_roles("SUPERADMIN")),
):
    cutoff = date.today() + timedelta(days=days)
    rows = db.scalars(select(CompanySubscription).where(
        CompanySubscription.status.in_(("TRIAL", "ACTIVE")),
        CompanySubscription.current_period_end <= cutoff,
    ).order_by(CompanySubscription.current_period_end)).all()
    return [{
        "company_id": row.company_id,
        "status": effective_status(row),
        "period_end": row.current_period_end,
        "trial_ends_on": row.trial_ends_on,
    } for row in rows if effective_status(row) in ("TRIAL", "ACTIVE")]


@router.get("/billing/subscriptions")
def list_company_subscriptions(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("SUPERADMIN")),
):
    rows = db.scalars(
        select(CompanySubscription)
        .order_by(CompanySubscription.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    results = []
    for subscription in rows:
        company = db.get(Company, subscription.company_id)
        summary = subscription_summary(db, subscription.company_id)
        results.append({
            "company_id": subscription.company_id,
            "company_name": company.name if company else None,
            "subscription": summary,
        })
    return results


@router.put("/billing/subscriptions/{company_id}/status")
def set_subscription_status(
    company_id: str,
    payload: SubscriptionStatusInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("SUPERADMIN")),
):
    subscription = db.scalar(select(CompanySubscription).where(
        CompanySubscription.company_id == company_id
    ))
    if not subscription:
        raise HTTPException(404, "Company subscription not found")
    if payload.status in ("ACTIVE", "TRIAL"):
        if not payload.valid_through or payload.valid_through < date.today():
            raise HTTPException(422, "A current or future valid_through date is required")
        subscription.current_period_end = payload.valid_through
        if payload.status == "TRIAL":
            subscription.trial_ends_on = payload.valid_through
        else:
            subscription.trial_ends_on = None
    else:
        subscription.trial_ends_on = None
    subscription.status = payload.status
    subscription.pending_plan_id = None
    subscription.pending_billing_cycle = None
    subscription.pending_effective_on = None
    company = db.get(Company, company_id)
    if company:
        company.is_active = payload.status != "SUSPENDED"
    _history(db, subscription, user, "STATUS_CHANGED", {
        "status": payload.status,
        "valid_through": payload.valid_through,
        "reason": payload.reason,
    })
    audit(db, company_id, user, "subscription.status_changed", "company_subscription", subscription.id, {
        "status": payload.status,
        "valid_through": payload.valid_through,
        "reason": payload.reason,
    })
    db.commit()
    return subscription_summary(db, company_id)


@router.get("/billing/usage")
def usage_summary(
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    today = date.today()
    period_start = today.replace(day=1)
    metrics = {
        "active_employees": len(db.scalars(select(Worker.id).where(
            Worker.company_id == company_id, Worker.is_active.is_(True)
        )).all()),
        "active_sites": len(db.scalars(select(Site.id).where(
            Site.company_id == company_id, Site.is_active.is_(True)
        )).all()),
    }
    for metric, quantity in metrics.items():
        snapshot = db.scalar(select(UsageSnapshot).where(
            UsageSnapshot.company_id == company_id,
            UsageSnapshot.period_start == period_start,
            UsageSnapshot.metric == metric,
        ))
        if snapshot:
            snapshot.quantity = quantity
            snapshot.measured_at = datetime.now(timezone.utc)
        else:
            db.add(UsageSnapshot(
                company_id=company_id, period_start=period_start,
                metric=metric, quantity=quantity,
            ))
    db.commit()
    subscription = db.scalar(select(CompanySubscription).where(
        CompanySubscription.company_id == company_id
    ))
    plan = db.get(SubscriptionPlan, subscription.plan_id) if subscription else None
    return {
        "period_start": period_start,
        "metrics": metrics,
        "limits": {
            "employees": plan.employee_limit if plan else None,
            "sites": plan.site_limit if plan else None,
        },
    }


@router.post("/billing/data-export")
def export_tenant_data(
    db: Session = Depends(get_db), user: User = Depends(require_roles("ADMIN")),
):
    company_id = require_company(user)
    exported = {}
    for table in Base.metadata.sorted_tables:
        if table.name == "companies":
            rows = db.execute(select(table).where(table.c.id == company_id)).mappings().all()
        elif "company_id" in table.c:
            rows = db.execute(select(table).where(table.c.company_id == company_id)).mappings().all()
        elif table.name == "employee_profiles":
            worker_ids = select(Worker.id).where(Worker.company_id == company_id)
            rows = db.execute(select(table).where(table.c.worker_id.in_(worker_ids))).mappings().all()
        else:
            continue
        if rows:
            exported[table.name] = [
                {key: value for key, value in dict(row).items() if key != "password_hash"}
                for row in rows
            ]
    audit(db, company_id, user, "company.data_exported", "company", company_id, {
        "tables": sorted(exported),
    })
    db.commit()
    return JSONResponse(
        content=json.loads(json.dumps({
            "company_id": company_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data": exported,
        }, default=str)),
        headers={"Content-Disposition": f'attachment; filename="company-{company_id}-export.json"'},
    )


@router.post("/billing/account-closure", status_code=201)
def request_account_closure(
    payload: ClosureInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN")),
):
    company_id = require_company(user)
    existing = db.scalar(select(AccountClosureRequest).where(
        AccountClosureRequest.company_id == company_id,
        AccountClosureRequest.status == "PENDING",
    ))
    if existing:
        raise HTTPException(409, "A pending account closure request already exists")
    request = AccountClosureRequest(
        company_id=company_id, requested_by=user.id, reason=payload.reason
    )
    db.add(request)
    db.flush()
    audit(db, company_id, user, "company.closure_requested", "account_closure_request", request.id)
    db.commit()
    return {"id": request.id, "status": request.status, "note": "Data is retained until an approved retention/deletion process is completed."}


@router.get("/billing/account-closure")
def get_account_closure_request(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    company_id = require_company(user)
    request = db.scalar(select(AccountClosureRequest).where(
        AccountClosureRequest.company_id == company_id
    ).order_by(AccountClosureRequest.created_at.desc()))
    if not request:
        return {"status": "NOT_REQUESTED"}
    return {
        "id": request.id,
        "status": request.status,
        "reason": request.reason,
        "review_note": request.review_note,
        "created_at": request.created_at,
        "reviewed_at": request.reviewed_at,
    }


@router.get("/billing/account-closure/requests")
def list_account_closure_requests(
    status: str | None = Query(default="PENDING", pattern=r"^(PENDING|APPROVED|REJECTED)$"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("SUPERADMIN")),
):
    query = select(AccountClosureRequest)
    if status:
        query = query.where(AccountClosureRequest.status == status)
    rows = db.scalars(query.order_by(
        AccountClosureRequest.created_at.desc()
    ).limit(limit)).all()
    return [{
        "id": row.id, "company_id": row.company_id, "requested_by": row.requested_by,
        "reason": row.reason, "status": row.status, "review_note": row.review_note,
        "created_at": row.created_at, "reviewed_at": row.reviewed_at,
    } for row in rows]


@router.put("/billing/account-closure/{request_id}/review")
def review_account_closure(
    request_id: str, payload: ClosureReviewInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("SUPERADMIN")),
):
    request = db.get(AccountClosureRequest, request_id)
    if not request:
        raise HTTPException(404, "Account closure request not found")
    if request.status != "PENDING":
        raise HTTPException(409, "Only pending account closure requests can be reviewed")
    request.status = payload.status
    request.reviewed_by = user.id
    request.review_note = payload.note
    request.reviewed_at = datetime.now(timezone.utc)
    if payload.status == "APPROVED":
        company = db.get(Company, request.company_id)
        if company:
            company.is_active = False
            users = db.scalars(select(User).where(User.company_id == request.company_id)).all()
            for tenant_user in users:
                tenant_user.is_active = False
        subscription = db.scalar(select(CompanySubscription).where(
            CompanySubscription.company_id == request.company_id
        ))
        if subscription:
            subscription.status = "SUSPENDED"
    audit(db, request.company_id, user, "company.closure_reviewed", "account_closure_request", request.id, {
        "status": payload.status, "note": payload.note,
    })
    db.commit()
    return {"id": request.id, "status": request.status, "company_deactivated": payload.status == "APPROVED"}


@router.post("/support/tickets", status_code=201)
def create_support_ticket(
    payload: TicketInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "MANAGER")),
):
    company_id = require_company(user)
    ticket = SupportTicket(
        company_id=company_id, created_by=user.id, subject=payload.subject,
        message=payload.message, priority=payload.priority,
    )
    db.add(ticket)
    db.flush()
    audit(db, company_id, user, "support.ticket_created", "support_ticket", ticket.id)
    db.commit()
    return _ticket_data(ticket)


def _ticket_data(ticket: SupportTicket) -> dict:
    return {
        "id": ticket.id, "subject": ticket.subject, "message": ticket.message,
        "status": ticket.status, "priority": ticket.priority,
        "staff_response": ticket.staff_response,
        "created_at": ticket.created_at, "updated_at": ticket.updated_at,
    }


@router.get("/support/tickets")
def list_support_tickets(
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    query = select(SupportTicket)
    if user.role != "SUPERADMIN":
        query = query.where(SupportTicket.company_id == require_company(user))
    rows = db.scalars(query.order_by(SupportTicket.created_at.desc()).limit(500)).all()
    return [_ticket_data(ticket) for ticket in rows]


@router.put("/support/tickets/{ticket_id}")
def review_support_ticket(
    ticket_id: str, payload: TicketReviewInput, db: Session = Depends(get_db),
    user: User = Depends(require_roles("SUPERADMIN")),
):
    ticket = db.get(SupportTicket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Support ticket not found")
    ticket.status = payload.status
    ticket.staff_response = payload.response
    ticket.updated_by = user.id
    audit(db, ticket.company_id, user, "support.ticket_updated", "support_ticket", ticket.id, {
        "status": payload.status,
    })
    db.commit()
    return _ticket_data(ticket)
