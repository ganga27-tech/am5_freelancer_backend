from datetime import date, datetime
from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator, model_validator
import re


# ----------------------------------------------------------------------
# Regex patterns for Indian Compliance
# ----------------------------------------------------------------------
PAN_REGEX = r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$"
GSTIN_REGEX = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"


# ----------------------------------------------------------------------
# Chart of Accounts Schemas
# ----------------------------------------------------------------------
class AccountBase(BaseModel):
    code: str = Field(..., description="Unique account ledger code, e.g., 1001, 2100", min_length=2, max_length=50)
    name: str = Field(..., min_length=2, max_length=200)
    category: str = Field(..., description="chartered, company, employee, freelancer")
    account_type: str = Field(..., description="asset, liability, equity, revenue, expense")
    parent_id: Optional[int] = None
    tier: int = Field(default=1, ge=1, le=4)
    currency: str = Field(default="INR", max_length=10)
    is_active: bool = True
    description: Optional[str] = None

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        allowed = {"chartered", "company", "employee", "freelancer"}
        if v.lower() not in allowed:
            raise ValueError(f"Category must be one of {allowed}")
        return v.lower()

    @field_validator("account_type")
    @classmethod
    def validate_account_type(cls, v: str) -> str:
        allowed = {"asset", "liability", "equity", "revenue", "expense"}
        if v.lower() not in allowed:
            raise ValueError(f"Account type must be one of {allowed}")
        return v.lower()


class AccountCreate(AccountBase):
    initial_balance: float = Field(default=0.0, description="Opening balance in INR")


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    account_type: Optional[str] = None
    parent_id: Optional[int] = None
    tier: Optional[int] = None
    is_active: Optional[bool] = None
    description: Optional[str] = None


class AccountResponse(AccountBase):
    id: int
    balance: float
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AccountTreeNode(AccountResponse):
    children: List["AccountTreeNode"] = []


# ----------------------------------------------------------------------
# Company Expense Schemas
# ----------------------------------------------------------------------
class ExpenseBase(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    category: str = Field(..., description="rent, utilities, software, marketing, travel, office_supplies, legal, other")
    vendor_name: str = Field(..., min_length=2, max_length=200)
    vendor_gstin: Optional[str] = None
    vendor_pan: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: date
    
    base_amount: float = Field(..., gt=0, description="Base amount before taxes")
    gst_rate: float = Field(default=0.0, ge=0.0, le=28.0, description="GST Rate in percent (0, 5, 12, 18, 28)")
    is_rcm: bool = Field(default=False, description="Reverse Charge Mechanism")
    is_interstate: bool = Field(default=False, description="True for IGST, False for CGST+SGST")
    
    tds_section: Optional[str] = Field(default=None, description="194C, 194J, 194I, etc.")
    tds_rate: float = Field(default=0.0, ge=0.0, le=30.0, description="TDS rate in percent")
    
    payment_mode: Optional[str] = Field(default="bank_transfer")
    receipt_url: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("vendor_gstin")
    @classmethod
    def validate_gstin(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.match(GSTIN_REGEX, v.strip().upper()):
            raise ValueError(f"Invalid GSTIN format: '{v}'. Must be 15 alphanumeric characters (e.g., 29ABCDE1234F1Z5)")
        return v.strip().upper() if v else None

    @field_validator("vendor_pan")
    @classmethod
    def validate_pan(cls, v: Optional[str]) -> Optional[str]:
        if v and not re.match(PAN_REGEX, v.strip().upper()):
            raise ValueError(f"Invalid PAN format: '{v}'. Must match 5 letters, 4 digits, 1 letter (e.g., ABCDE1234F)")
        return v.strip().upper() if v else None


class ExpenseCreate(ExpenseBase):
    pass


class ExpenseUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = None
    vendor_pan: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    base_amount: Optional[float] = Field(default=None, gt=0)
    gst_rate: Optional[float] = Field(default=None, ge=0.0, le=28.0)
    is_rcm: Optional[bool] = None
    is_interstate: Optional[bool] = None
    tds_section: Optional[str] = None
    tds_rate: Optional[float] = Field(default=None, ge=0.0, le=30.0)
    payment_mode: Optional[str] = None
    payment_status: Optional[str] = None
    payment_date: Optional[date] = None
    payment_reference: Optional[str] = None
    receipt_url: Optional[str] = None
    notes: Optional[str] = None


class ExpenseResponse(ExpenseBase):
    id: int
    expense_code: str
    gst_amount: float
    tds_amount: float
    total_amount: float
    net_payable_amount: float
    payment_status: str
    payment_date: Optional[date] = None
    payment_reference: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ----------------------------------------------------------------------
# Freelancer & Contractor Schemas
# ----------------------------------------------------------------------
class FreelancerCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    email: str = Field(..., max_length=150)
    phone: str = Field(..., min_length=10, max_length=20)
    pan_number: str = Field(...)
    gstin: Optional[str] = None
    service_type: str = Field(..., max_length=100)
    tds_applicable_section: str = Field(default="194J")
    tds_default_rate: float = Field(default=10.0, ge=0.0, le=30.0)
    bank_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_ifsc_code: Optional[str] = None
    bank_beneficiary_name: Optional[str] = None

    @field_validator("pan_number")
    @classmethod
    def validate_fl_pan(cls, v: str) -> str:
        if not re.match(PAN_REGEX, v.strip().upper()):
            raise ValueError(f"Invalid PAN format: '{v}'. Example: ABCDE1234F")
        return v.strip().upper()


class FreelancerResponse(BaseModel):
    id: int
    freelancer_code: str
    name: str
    email: str
    phone: str
    pan_number: str
    gstin: Optional[str]
    service_type: str
    tds_applicable_section: str
    tds_default_rate: float
    bank_name: Optional[str]
    bank_account_number: Optional[str]
    bank_ifsc_code: Optional[str]
    bank_beneficiary_name: Optional[str]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class FreelancerInvoiceCreate(BaseModel):
    contractor_id: int
    invoice_number: str = Field(..., min_length=1, max_length=100)
    invoice_date: date
    description: str
    period_month: str = Field(..., description="e.g. '2026-09'")
    gross_amount: float = Field(..., gt=0)
    gst_rate: float = Field(default=0.0, ge=0.0, le=28.0)
    tds_section: str = Field(default="194J")
    tds_rate: float = Field(default=10.0, ge=0.0, le=30.0)
    invoice_document_url: Optional[str] = None


class FreelancerInvoiceResponse(BaseModel):
    id: int
    contractor_id: int
    invoice_number: str
    invoice_date: date
    description: str
    period_month: str
    gross_amount: float
    gst_rate: float
    gst_amount: float
    tds_section: str
    tds_rate: float
    tds_amount: float
    net_payable_amount: float
    status: str
    payment_mode: Optional[str]
    payment_date: Optional[date]
    payment_reference: Optional[str]
    created_at: datetime
    contractor_name: Optional[str] = None

    class Config:
        from_attributes = True


# ----------------------------------------------------------------------
# Payroll Schemas
# ----------------------------------------------------------------------
class PayrollRecordInput(BaseModel):
    employee_id: int
    basic_salary: float = Field(..., ge=0)
    hra: float = Field(default=0.0, ge=0)
    special_allowance: float = Field(default=0.0, ge=0)
    tds_withheld: Optional[float] = Field(default=None, ge=0)
    other_deductions: float = Field(default=0.0, ge=0)


class PayrollBatchCreate(BaseModel):
    month_year: str = Field(..., description="Format: YYYY-MM (e.g. 2026-09)")
    employee_records: Optional[List[PayrollRecordInput]] = None


class PayrollEmployeeRecordResponse(BaseModel):
    id: int
    batch_id: int
    employee_id: int
    employee_name: Optional[str] = None
    employee_email: Optional[str] = None
    employee_role: Optional[str] = None
    basic_salary: float
    hra: float
    special_allowance: float
    gross_salary: float
    pf_employee: float
    pf_employer: float
    esi_employee: float
    esi_employer: float
    tds_withheld: float
    other_deductions: float
    total_deductions: float
    net_salary: float
    payment_status: str
    payment_date: Optional[date]
    payment_reference: Optional[str]
    payslip_pdf_url: Optional[str]

    class Config:
        from_attributes = True


class PayrollBatchResponse(BaseModel):
    id: int
    batch_code: str
    month_year: str
    total_employees: int
    total_gross: float
    total_pf_deduction: float
    total_esi_deduction: float
    total_tds_deduction: float
    total_net_disbursed: float
    status: str
    disbursement_date: Optional[date]
    created_at: datetime
    records: List[PayrollEmployeeRecordResponse] = []

    class Config:
        from_attributes = True


# ----------------------------------------------------------------------
# Journal Entry (General Ledger) Schemas
# ----------------------------------------------------------------------
class JournalLineInput(BaseModel):
    debit_account_id: Optional[int] = None
    credit_account_id: Optional[int] = None
    amount: float = Field(..., gt=0)
    description: Optional[str] = None

    @model_validator(mode="after")
    def validate_one_side_set(self):
        has_debit = self.debit_account_id is not None
        has_credit = self.credit_account_id is not None
        if not has_debit and not has_credit:
            raise ValueError("Line must specify either debit_account_id or credit_account_id")
        if has_debit and has_credit:
            raise ValueError("Line cannot have both debit_account_id and credit_account_id set simultaneously")
        return self


class JournalEntryCreate(BaseModel):
    entry_date: date
    voucher_type: str = Field(..., description="expense, payroll, freelancer_payment, tax_payment, manual_journal")
    reference_id: Optional[str] = None
    narration: str = Field(..., min_length=3)
    lines: List[JournalLineInput] = Field(..., min_length=2)

    @model_validator(mode="after")
    def validate_balanced_voucher(self):
        total_debit = sum(line.amount for line in self.lines if line.debit_account_id is not None)
        total_credit = sum(line.amount for line in self.lines if line.credit_account_id is not None)
        if round(total_debit, 2) != round(total_credit, 2):
            raise ValueError(f"Journal entry is unbalanced: Total Debits (₹{total_debit:.2f}) != Total Credits (₹{total_credit:.2f})")
        return self


class JournalLineResponse(BaseModel):
    id: int
    debit_account_id: Optional[int]
    credit_account_id: Optional[int]
    debit_account_name: Optional[str] = None
    credit_account_name: Optional[str] = None
    amount: float
    description: Optional[str]

    class Config:
        from_attributes = True


class JournalEntryResponse(BaseModel):
    id: int
    voucher_number: str
    entry_date: date
    voucher_type: str
    reference_id: Optional[str]
    narration: str
    total_debit: float
    total_credit: float
    status: str
    created_at: datetime
    lines: List[JournalLineResponse] = []

    class Config:
        from_attributes = True


# ----------------------------------------------------------------------
# Statutory Compliance Schemas (GST & TDS)
# ----------------------------------------------------------------------
class GstSummaryResponse(BaseModel):
    filing_period: str
    taxable_sales: float
    output_cgst: float
    output_sgst: float
    output_igst: float
    total_output_tax: float
    eligible_itc_cgst: float
    eligible_itc_sgst: float
    eligible_itc_igst: float
    total_itc_claimed: float
    net_tax_payable: float
    status: str


class TdsChallanCreate(BaseModel):
    challan_number: str
    bsr_code: str = Field(..., min_length=7, max_length=7, description="7-digit Bank BSR Code")
    deposit_date: date
    section: str = Field(..., description="192, 194C, 194J, 194I")
    financial_year: str = Field(..., description="e.g. 2026-27")
    quarter: str = Field(..., description="Q1, Q2, Q3, Q4")
    tax_amount: float = Field(..., gt=0)
    surcharge: float = Field(default=0.0, ge=0)
    cess: float = Field(default=0.0, ge=0)
    interest_fee: float = Field(default=0.0, ge=0)
    cin_number: Optional[str] = None
    bank_reference: Optional[str] = None


class TdsChallanResponse(BaseModel):
    id: int
    challan_number: str
    bsr_code: str
    deposit_date: date
    section: str
    financial_year: str
    quarter: str
    tax_amount: float
    surcharge: float
    cess: float
    interest_fee: float
    total_deposit: float
    cin_number: Optional[str]
    bank_reference: Optional[str]
    status: str

    class Config:
        from_attributes = True


# ----------------------------------------------------------------------
# Dashboard & Reports Schemas
# ----------------------------------------------------------------------
class FinancialDashboardStats(BaseModel):
    total_cash_bank_balance: float
    total_inflows_month: float
    total_outflows_month: float
    net_profit_month: float
    pending_vendor_bills: float
    pending_payroll: float
    pending_freelancer_payouts: float
    statutory_tax_liability: float
    recent_transactions: List[JournalEntryResponse] = []
    expense_category_distribution: Dict[str, float] = {}


class ProfitLossReport(BaseModel):
    start_date: date
    end_date: date
    total_revenue: float
    cost_of_services: float
    gross_profit: float
    operating_expenses: Dict[str, float]
    total_operating_expenses: float
    net_operating_income: float
    tax_expense: float
    net_profit_after_tax: float
