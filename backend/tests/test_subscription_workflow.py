import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.main as main
import app.subscriptions as subscriptions


class SubscriptionWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        main.Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        self.company = main.Company(
            name="Subscription Tenant", code="SUB_TENANT", is_active=True
        )
        self.other_company = main.Company(
            name="Other Tenant", code="OTHER_TENANT", is_active=True
        )
        self.db.add_all([self.company, self.other_company])
        self.db.flush()
        self.admin = main.User(
            username="subscription-admin",
            email="subscription-admin@example.test",
            password_hash="must-not-be-exported",
            role="ADMIN",
            company_id=self.company.id,
            is_active=True,
        )
        self.superadmin = main.User(
            username="subscription-superadmin",
            email="subscription-superadmin@example.test",
            password_hash="test-hash",
            role="SUPERADMIN",
            company_id=None,
            is_active=True,
        )
        self.other_admin = main.User(
            username="other-admin",
            email="other-admin@example.test",
            password_hash="test-hash",
            role="ADMIN",
            company_id=self.other_company.id,
            is_active=True,
        )
        self.site = main.Site(
            company_id=self.company.id, name="Subscription Site", is_active=True
        )
        self.db.add_all([self.admin, self.superadmin, self.other_admin, self.site])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_limits_entitlements_invoice_reconciliation_and_license(self):
        plan_response = subscriptions.create_plan(
            subscriptions.PlanInput(
                code="STARTER",
                name="Starter",
                monthly_company_fee_mmk=10000,
                monthly_employee_fee_mmk=1500,
                employee_limit=1,
                site_limit=1,
                features=["payroll"],
            ),
            self.db,
            self.superadmin,
        )
        subscriptions.start_trial(
            subscriptions.StartTrialInput(plan_id=plan_response["id"]),
            self.db,
            self.admin,
        )
        with self.assertRaises(main.HTTPException) as site_limit:
            main.create_site(
                main.SiteInput(name="Over-limit Site"),
                self.db,
                self.admin,
            )
        self.assertEqual(site_limit.exception.status_code, 409)

        created = main.create_worker(
            main.WorkerInput(
                employee_code="SUB-001",
                full_name="Subscription Guard",
                monthly_salary_mmk=500000,
                site_id=self.site.id,
            ),
            self.db,
            self.admin,
        )
        self.assertTrue(created["id"])
        with self.assertRaises(main.HTTPException) as raised:
            main.create_worker(
                main.WorkerInput(
                    employee_code="SUB-002",
                    full_name="Second Guard",
                    monthly_salary_mmk=500000,
                ),
                self.db,
                self.admin,
            )
        self.assertEqual(raised.exception.status_code, 409)

        with self.assertRaises(main.HTTPException) as denied:
            subscriptions.assert_subscription_access(
                self.db, self.company.id, feature="attendance"
            )
        self.assertEqual(denied.exception.status_code, 403)

        invoice = subscriptions.issue_invoice(self.db, self.admin)
        self.assertEqual(invoice["amount_mmk"], 11500)
        receipt = subscriptions.submit_receipt(
            invoice["id"],
            subscriptions.ReceiptInput(reference="BANK-RECEIPT-001"),
            self.db,
            self.admin,
        )
        self.assertEqual(receipt["status"], "PENDING_REVIEW")
        confirmed = subscriptions.confirm_invoice_payment(
            invoice["id"], self.db, self.superadmin
        )
        self.assertEqual(confirmed["status"], "PAID")
        self.assertFalse(confirmed["payment_provider_initiated"])
        license_status = subscriptions.validate_license(self.db, self.admin)
        self.assertTrue(license_status["valid"])
        self.assertEqual(license_status["status"], "ACTIVE")

    def test_upgrade_and_annual_invoice_use_scheduled_plan(self):
        starter = subscriptions.create_plan(
            subscriptions.PlanInput(
                code="UPGRADE_START",
                name="Upgrade start",
                monthly_company_fee_mmk=1000,
            ),
            self.db,
            self.superadmin,
        )
        enterprise = subscriptions.create_plan(
            subscriptions.PlanInput(
                code="UPGRADE_ENTERPRISE",
                name="Upgrade enterprise",
                monthly_company_fee_mmk=10000,
                monthly_employee_fee_mmk=1000,
            ),
            self.db,
            self.superadmin,
        )
        subscriptions.start_trial(
            subscriptions.StartTrialInput(plan_id=starter["id"]),
            self.db,
            self.admin,
        )
        change = subscriptions.request_plan_change(
            subscriptions.PlanChangeInput(
                plan_id=enterprise["id"],
                billing_cycle="ANNUAL",
            ),
            self.db,
            self.admin,
        )
        self.assertEqual(change["status"], "SCHEDULED")
        invoice = subscriptions.issue_invoice(self.db, self.admin)
        self.assertEqual(invoice["plan_id"], enterprise["id"])
        self.assertEqual(invoice["amount_mmk"], 120000)
        self.assertGreater(invoice["service_end"], invoice["service_start"])

        subscriptions.submit_receipt(
            invoice["id"],
            subscriptions.ReceiptInput(reference="ANNUAL-RECEIPT-001"),
            self.db,
            self.admin,
        )
        subscriptions.confirm_invoice_payment(
            invoice["id"], self.db, self.superadmin
        )
        license_status = subscriptions.validate_license(self.db, self.admin)
        self.assertEqual(license_status["plan"]["id"], enterprise["id"])
        self.assertEqual(license_status["billing_cycle"], "ANNUAL")

    def test_tenant_export_excludes_other_tenant_and_password_hashes(self):
        own_worker = main.Worker(
            company_id=self.company.id,
            employee_code="OWN-001",
            full_name="Own Guard",
            phone="",
            monthly_salary_mmk=100000,
            is_active=True,
        )
        other_worker = main.Worker(
            company_id=self.other_company.id,
            employee_code="OTHER-001",
            full_name="Other Guard",
            phone="",
            monthly_salary_mmk=100000,
            is_active=True,
        )
        self.db.add_all([own_worker, other_worker])
        self.db.commit()

        response = subscriptions.export_tenant_data(self.db, self.admin)
        data = json.loads(response.body)
        exported = data["data"]
        self.assertEqual(
            [row["employee_code"] for row in exported["workers"]],
            ["OWN-001"],
        )
        self.assertNotIn("password_hash", json.dumps(exported))
        self.assertEqual(data["company_id"], self.company.id)

    def test_worker_api_lookup_is_tenant_scoped(self):
        foreign_worker = main.Worker(
            company_id=self.other_company.id,
            employee_code="FOREIGN-001",
            full_name="Foreign Guard",
            phone="",
            monthly_salary_mmk=100000,
            is_active=True,
        )
        self.db.add(foreign_worker)
        self.db.commit()

        with self.assertRaises(main.HTTPException) as raised:
            main.get_worker(foreign_worker.id, self.db, self.admin)
        self.assertEqual(raised.exception.status_code, 404)

        with self.assertRaises(main.HTTPException) as role_denial:
            main.require_roles("SUPERADMIN")(self.admin)
        self.assertEqual(role_denial.exception.status_code, 403)

    def test_suspended_subscription_blocks_application_but_allows_billing(self):
        plan = subscriptions.create_plan(
            subscriptions.PlanInput(code="STATUS", name="Status test"),
            self.db,
            self.superadmin,
        )
        subscriptions.start_trial(
            subscriptions.StartTrialInput(plan_id=plan["id"]),
            self.db,
            self.admin,
        )
        subscriptions.set_subscription_status(
            self.company.id,
            subscriptions.SubscriptionStatusInput(
                status="SUSPENDED",
                reason="Past due after notice",
            ),
            self.db,
            self.superadmin,
        )
        with self.assertRaises(main.HTTPException) as blocked:
            subscriptions.enforce_company_subscription_status(
                self.db, self.admin, "/api/v1/workers"
            )
        self.assertEqual(blocked.exception.status_code, 402)
        subscriptions.enforce_company_subscription_status(
            self.db, self.admin, "/api/v1/billing/invoices"
        )


if __name__ == "__main__":
    unittest.main()
