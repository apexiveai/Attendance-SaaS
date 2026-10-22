import unittest
from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.main as main
import app.operations as operations


class PayrollWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        main.Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)

        self.company = main.Company(
            name="Workflow Test Company", code="WORKFLOW_TEST", is_active=True
        )
        self.db.add(self.company)
        self.db.flush()
        self.admin = main.User(
            username="workflow-admin",
            email="workflow-admin@example.test",
            password_hash="test-hash",
            role="ADMIN",
            company_id=self.company.id,
            is_active=True,
        )
        self.approver = main.User(
            username="workflow-approver",
            email="workflow-approver@example.test",
            password_hash="test-hash",
            role="PAYROLL",
            company_id=self.company.id,
            is_active=True,
        )
        self.site = main.Site(
            company_id=self.company.id,
            name="Test Site",
            address="",
            is_active=True,
        )
        self.db.add_all([self.admin, self.approver, self.site])
        self.db.flush()
        self.worker = main.Worker(
            company_id=self.company.id,
            site_id=self.site.id,
            employee_code="GUARD-001",
            full_name="Test Guard",
            phone="",
            monthly_salary_mmk=600000,
            is_active=True,
        )
        self.db.add(self.worker)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def assert_http_error(self, status_code, callback):
        with self.assertRaises(main.HTTPException) as raised:
            callback()
        self.assertEqual(raised.exception.status_code, status_code)

    def test_payroll_formula_components_and_deduction_guard(self):
        components = operations.calculate_payroll_amounts(
            wage_basis="MONTHLY",
            rate=600000,
            fixed_allowance=50000,
            worked_days=26,
            scheduled_days=26,
            worked_hours=208,
            overtime_hours=2,
            night_shifts=3,
            night_allowance=5000,
            overtime_multiplier=1.5,
            loan_repayment=30000,
            unpaid_leave_days=1,
        )
        totals = {
            "earnings": sum(row["amount_mmk"] for row in components if row["type"] == "EARNING"),
            "deductions": sum(row["amount_mmk"] for row in components if row["type"] == "DEDUCTION"),
        }
        self.assertEqual(totals["earnings"], 673654)
        self.assertEqual(totals["deductions"], 53077)
        self.assertEqual(totals["earnings"] - totals["deductions"], 620577)

        self.assert_http_error(422, lambda: operations.calculate_payroll_amounts(
            wage_basis="DAILY",
            rate=1000,
            fixed_allowance=0,
            worked_days=1,
            scheduled_days=1,
            worked_hours=8,
            overtime_hours=0,
            night_shifts=0,
            night_allowance=0,
            overtime_multiplier=1.5,
            loan_repayment=2000,
            unpaid_leave_days=0,
        ))

    def test_calculation_version_approval_payment_and_reopen(self):
        operations.set_salary(
            self.worker.id,
            operations.SalaryInput(
                wage_basis="MONTHLY",
                base_rate_mmk=600000,
                fixed_allowance_mmk=50000,
                effective_from=date(2026, 1, 1),
            ),
            self.db,
            self.admin,
        )
        attendance = main.create_attendance(
            main.AttendanceInput(
                worker_id=self.worker.id,
                site_id=self.site.id,
                work_date=date(2026, 1, 5),
                shift="DAY",
                attendance_status="PRESENT",
                check_in_at=datetime(2026, 1, 5, 8, tzinfo=timezone.utc),
                check_out_at=datetime(2026, 1, 5, 18, tzinfo=timezone.utc),
            ),
            self.db,
            self.admin,
        )
        operations.approve_overtime(
            attendance["id"],
            operations.OvertimeInput(approved_hours=2),
            self.db,
            self.admin,
        )
        leave = operations.request_leave(
            operations.LeaveInput(
                worker_id=self.worker.id,
                leave_type="UNPAID",
                start_date=date(2026, 1, 15),
                end_date=date(2026, 1, 15),
            ),
            self.db,
            self.admin,
        )
        operations.review_leave(
            leave["id"],
            operations.ReviewInput(status="APPROVED", note="Reviewed"),
            self.db,
            self.admin,
        )
        loan = operations.request_loan(
            operations.LoanInput(
                worker_id=self.worker.id,
                kind="LOAN",
                principal_mmk=60000,
                monthly_repayment_mmk=30000,
            ),
            self.db,
            self.admin,
        )
        operations.review_loan(
            loan["id"],
            operations.ReviewInput(status="APPROVED", note="Reviewed"),
            self.db,
            self.admin,
        )
        claim = operations.create_claim(
            operations.ClaimInput(
                worker_id=self.worker.id,
                claim_date=date(2026, 1, 20),
                category="TRAVEL",
                amount_mmk=20000,
                note="Receipt reviewed",
            ),
            self.db,
            self.admin,
        )
        operations.review_claim(
            claim["id"],
            operations.ReviewInput(status="APPROVED", note="Reviewed"),
            self.db,
            self.admin,
        )

        operations.lock_attendance_period(
            2026,
            1,
            operations.PeriodReasonInput(reason="Attendance reviewed"),
            self.db,
            self.admin,
        )
        result = operations.calculate_period(
            2026, 1, False, "period-run-1", self.db, self.admin
        )
        self.assertEqual(result["status"], "CALCULATED")
        self.assertEqual(result["version"], 1)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(
            operations.calculate_period(
                2026, 1, False, "period-run-1", self.db, self.admin
            ),
            result,
        )
        unchanged = operations.calculate_period(
            2026, 1, False, "period-run-unchanged", self.db, self.admin
        )
        self.assertFalse(unchanged["recalculated"])
        self.assertEqual(unchanged["version"], 1)

        operations.set_salary(
            self.worker.id,
            operations.SalaryInput(
                wage_basis="MONTHLY",
                base_rate_mmk=650000,
                fixed_allowance_mmk=50000,
                effective_from=date(2026, 1, 15),
            ),
            self.db,
            self.admin,
        )
        self.assert_http_error(
            409,
            lambda: operations.calculate_period(
                2026, 1, False, "changed-without-recalc", self.db, self.admin
            ),
        )
        recalculated = operations.calculate_period(
            2026, 1, True, "period-run-2", self.db, self.admin
        )
        self.assertEqual(recalculated["version"], 2)
        self.assertTrue(recalculated["recalculated"])

        operations.submit_payroll_period(2026, 1, self.db, self.admin)
        self.assert_http_error(
            403,
            lambda: operations.approve_payroll_period(
                2026,
                1,
                operations.PeriodReasonInput(reason="Approval"),
                self.db,
                self.admin,
            ),
        )
        operations.approve_payroll_period(
            2026,
            1,
            operations.PeriodReasonInput(reason="Second-person review"),
            self.db,
            self.approver,
        )
        payroll_id = recalculated["results"][0]["payroll_id"]
        slip = operations.payslip(payroll_id, self.db, self.approver)
        self.assertGreater(slip["net_pay_mmk"], 0)
        self.assertEqual(slip["period_status"], "APPROVED")

        payment = operations.record_payment(
            payroll_id,
            operations.PaymentInput(
                amount_mmk=slip["net_pay_mmk"],
                payment_date=date(2026, 2, 1),
                payment_method="CASH",
                reference="WORKFLOW-REF-001",
            ),
            self.db,
            self.approver,
        )
        self.assertEqual(payment["period_status"], "PAID")
        self.assertFalse(payment["bank_transfer_initiated"])
        operations.lock_payroll_period(
            2026,
            1,
            operations.PeriodReasonInput(reason="All payments reconciled"),
            self.db,
            self.approver,
        )
        operations.grant_reopen_permission(
            self.admin.id, self.db, self.admin
        )
        reopened = operations.reopen_payroll_period(
            2026,
            1,
            operations.PeriodReasonInput(reason="Authorized review"),
            self.db,
            self.admin,
        )
        self.assertEqual(reopened["status"], "PAID")

    def test_attendance_cannot_be_added_after_period_lock(self):
        operations.lock_attendance_period(
            2026,
            1,
            operations.PeriodReasonInput(reason="Review complete"),
            self.db,
            self.admin,
        )
        self.assert_http_error(
            409,
            lambda: main.create_attendance(
                main.AttendanceInput(
                    worker_id=self.worker.id,
                    site_id=self.site.id,
                    work_date=date(2026, 1, 5),
                    shift="DAY",
                    attendance_status="PRESENT",
                ),
                self.db,
                self.admin,
            ),
        )


if __name__ == "__main__":
    unittest.main()
