# Workforce and payroll operations API

The mobile app's existing visual theme is unchanged. The API additions are under
`/api/v1`; authenticate with the existing bearer-token login endpoint. Company
records are tenant-scoped.

## Payroll period workflow

1. Maintain employee profiles, effective-dated salary history and attendance.
2. Review pending attendance evidence and corrections, then lock attendance:
   `POST /api/v1/attendance/periods/{year}/{month}/lock`.
3. Calculate payroll:
   `POST /api/v1/payroll/calculate?year=2026&month=10`.
   An optional `Idempotency-Key` makes retries return the original response.
   If source records changed after calculation, explicitly request
   `&recalculate=true`; this creates a new audited version.
4. Submit the calculated period for approval. A different user must approve it
   with a reason.
5. Record manual payment confirmations or payment attempts. No bank or wallet
   transfer is initiated by this API. Partial payments are supported.
6. Lock a fully paid period. Reopening requires a separately granted
   `PAYROLL_REOPEN` permission. Corrections to a locked period must be approved
   and are applied to the next payroll period as a separate adjustment.

Direct client-entered payroll creation and per-employee approval are disabled;
use period calculation and approval so amounts are derived from server records.

The calculation currently supports monthly, daily, hourly and shift salary
bases, fixed allowances, approved overtime, configured night allowances,
unpaid leave, approved loan/advance repayments, approved expense reimbursements,
deduction caps and approved adjustments. Policies are company-specific and
audited. The default calculation does not infer or apply tax or SSB amounts.

## Other operations

- Employee profiles, documents/training records, account linking, effective-date
  site assignment and salary history are exposed under `/workers`.
- Shift definitions, rosters, swap requests and staffing reports are available
  under `/shifts`, `/roster` and `/reports/staffing`.
- Leave requests and entitlements are exposed under `/leave-requests` and
  `/workers/{worker_id}/leave-entitlements/...`.
- Photo evidence stores a reference URL and optional consented GPS/OCR text.
  Company policy controls whether photo, GPS and OCR text are accepted. OCR
  text capture is not an OCR engine or identity verification.
- Payslip data is available as JSON. Payroll reports can be exported as CSV or
  XLSX. Payment attempts require manual reconciliation and confirmation.
- Tax, SSB, minimum-wage and other compliance rule configurations are
  effective-dated, audited records for accountant review; saving a rule does
  not automatically apply it or certify legal compliance.

## SaaS subscription and support operations

- Superadmins manage plans at `POST/PUT /api/v1/billing/plans`. Plans define
  monthly company and employee charges, employee/site caps, and feature keys.
- A tenant admin can start one 14-day trial at
  `POST /api/v1/billing/trial`. The tenant can inspect status and the license
  response at `GET /api/v1/billing/subscription` and
  `GET /api/v1/billing/license`.
- Employee/site caps are checked when creating records. The `attendance` and
  `payroll` feature keys are checked on attendance creation and payroll runs.
  Expired and suspended tenants are blocked from application APIs while
  billing, support, and the current-user endpoint remain available.
  Individual feature keys on other operational endpoints are not yet
  comprehensively enforced.
  Companies without a subscription retain legacy access; production tenant
  onboarding must assign a subscription before removing this compatibility
  behavior.
- Plan and billing-cycle changes are scheduled for the next service period.
  Invoices meter active employees and are issued for monthly or annual service.
  A tenant may submit a receipt reference; a superadmin must reconcile it
  before the invoice is marked paid. This API does not connect to or initiate
  bank, wallet, or card payments.
- `GET /api/v1/billing/renewals/due` provides a reminder queue; it does not
  send email/SMS notifications. `GET /api/v1/billing/usage` records a monthly
  employee/site usage snapshot when requested.
- Company admins can open support tickets, request a tenant JSON data export,
  and request account closure. Closure approval deactivates the company and
  its users but deliberately retains records; it is not a physical data
  deletion or an account-erasure guarantee.

## Technical readiness and deployment boundaries

- The API remains versioned under `/api/v1`. PostgreSQL is supported by the
  SQLAlchemy engine. A forward-only Alembic baseline is available:
  `alembic upgrade head` from `backend/`. For an existing database previously
  created by `create_all`, review its schema and Alembic version state before
  migration; the baseline creates missing tables but does not alter existing
  columns. Production startup does not create or mutate tables; apply
  migrations before deploying the application. Use forward fixes/restore a
  verified backup rather than downgrading the baseline.
- Payroll calculation uses a PostgreSQL transaction-scoped advisory lock per
  company/period and a row lock for existing period records. The existing
  unit tests exercise calculation, idempotency, approvals and payment
  reconciliation; subscription tests cover quotas, entitlements, tenant
  export and invoice reconciliation.
- HTTP request logs are JSON and include a request ID, status, path, and
  duration. No external error-monitoring service is configured. There is no
  shared rate-limit/abuse-prevention service yet.
- Photo/receipt binaries are not uploaded by the API, so MIME/signature upload
  validation, private object storage, and retention deletion are not yet
  implemented. Do not store private documents at public URLs.
- No backup scheduler, restore-verification job, production deployment
  manifests, or automatic rollback system is included. Backups and restore
  drills must be configured for the selected PostgreSQL provider. Deploy
  schema changes as forward migrations and retain the previous application
  release for application rollback.
- Android preview/store EAS build profiles are present in `mobile/eas.json`;
  EAS signing credentials, a completed signed build, and a Play Store release
  have not been configured or verified.
- The mobile app has no billing/auth/API integration. Actual bank integration, accounting integration,
  offline synchronization, and statutory PIT/SSB automation remain separate
  production tasks.

## Not yet implemented

The API does not provide binary photo/receipt storage, an OCR processor, duplicate
photo detection, offline mobile synchronization, PDF payslip generation, bank
file layouts or bank/wallet integrations. The mobile app's module directory is
navigation/information only and is not yet connected to these APIs. Company
logo upload and automated statutory calculations also require additional
storage, jurisdiction-specific review and implementation.
