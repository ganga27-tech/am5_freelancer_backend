import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import unittest
from datetime import date
from pydantic import ValidationError


from app.schemas.accounting import (
    ExpenseCreate,
    FreelancerCreate,
    JournalEntryCreate,
    JournalLineInput,
)
from app.services.accounting_service import AccountingCalculationEngine, round_cur


class TestAccountingCalculationEngine(unittest.TestCase):
    def setUp(self):
        self.calc = AccountingCalculationEngine()

    def test_gst_and_tds_expense_calculation(self):
        # Scenario: Software subscription / Consulting invoice
        # Base: 100,000 | GST 18% | TDS 194J @ 10%
        result = self.calc.calculate_expense_taxes(
            base_amount=100000.0,
            gst_rate=18.0,
            is_rcm=False,
            tds_rate=10.0,
        )
        self.assertEqual(result["base_amount"], 100000.0)
        self.assertEqual(result["gst_amount"], 18000.0)
        self.assertEqual(result["tds_amount"], 10000.0)
        self.assertEqual(result["total_amount"], 118000.0)
        self.assertEqual(result["net_payable_amount"], 108000.0)

    def test_rcm_expense_calculation(self):
        # Scenario: Legal advice under RCM (Company pays GST directly to Govt)
        # Base: 50,000 | GST 18% | TDS 10% | is_rcm = True
        result = self.calc.calculate_expense_taxes(
            base_amount=50000.0,
            gst_rate=18.0,
            is_rcm=True,
            tds_rate=10.0,
        )
        self.assertEqual(result["gst_amount"], 9000.0)
        self.assertEqual(result["tds_amount"], 5000.0)
        # Net payable to vendor should not include RCM GST: 50000 - 5000 = 45000
        self.assertEqual(result["net_payable_amount"], 45000.0)

    def test_payroll_deductions_calculation(self):
        # Scenario: Employee with Basic: 30,000, HRA: 15,000, Special: 10,000 -> Gross: 55,000
        result = self.calc.calculate_payroll_deductions(
            basic=30000.0,
            hra=15000.0,
            special_allowance=10000.0,
            custom_tds=2500.0,
            other_deductions=500.0,
        )
        self.assertEqual(result["gross_salary"], 55000.0)
        # PF: 12% of 15000 cap = 1800.0
        self.assertEqual(result["pf_employee"], 1800.0)
        # ESI: Gross > 21000 => 0.0
        self.assertEqual(result["esi_employee"], 0.0)
        self.assertEqual(result["tds_withheld"], 2500.0)
        self.assertEqual(result["total_deductions"], 1800.0 + 2500.0 + 500.0)
        self.assertEqual(result["net_salary"], 55000.0 - 4800.0)

    def test_pan_and_gstin_pydantic_validations(self):
        # Valid Expense
        exp = ExpenseCreate(
            title="Cloud Hosting",
            category="software",
            vendor_name="Amazon Web Services India",
            vendor_gstin="29ABCDE1234F1Z5",
            vendor_pan="ABCDE1234F",
            invoice_date=date.today(),
            base_amount=25000.0,
            gst_rate=18.0,
        )
        self.assertEqual(exp.vendor_pan, "ABCDE1234F")

        # Invalid PAN format should raise ValidationError
        with self.assertRaises(ValidationError):
            ExpenseCreate(
                title="Invalid Vendor",
                category="software",
                vendor_name="Invalid",
                vendor_pan="INVALID_PAN_123",
                invoice_date=date.today(),
                base_amount=1000.0,
            )

        # Invalid GSTIN format should raise ValidationError
        with self.assertRaises(ValidationError):
            ExpenseCreate(
                title="Invalid Vendor",
                category="software",
                vendor_name="Invalid",
                vendor_gstin="12345",
                invoice_date=date.today(),
                base_amount=1000.0,
            )

    def test_journal_entry_balance_validation(self):
        # Balanced Journal Entry should succeed
        entry = JournalEntryCreate(
            entry_date=date.today(),
            voucher_type="manual_journal",
            narration="Test Balanced Entry",
            lines=[
                JournalLineInput(debit_account_id=1, amount=15000.0, description="Debit Expense"),
                JournalLineInput(credit_account_id=2, amount=15000.0, description="Credit Bank"),
            ],
        )
        self.assertEqual(len(entry.lines), 2)

        # Unbalanced Journal Entry should fail
        with self.assertRaises(ValidationError):
            JournalEntryCreate(
                entry_date=date.today(),
                voucher_type="manual_journal",
                narration="Test Unbalanced Entry",
                lines=[
                    JournalLineInput(debit_account_id=1, amount=15000.0),
                    JournalLineInput(credit_account_id=2, amount=10000.0),  # Mismatched credit
                ],
            )


if __name__ == "__main__":
    unittest.main()
