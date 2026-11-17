from sqlalchemy import (
    Column,
    String,
    Integer,
    BigInteger,
    ForeignKey,
    DateTime,
    Text,
    Boolean,
    Float,
    Numeric,
    JSON,
    Date,
    Enum,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base_class import Base


class Account(Base):
    __tablename__ = "accounting_accounts"

    id = Column(BigInteger, primary_key=True, index=True)
    code = Column(String(50), unique=True, nullable=False, index=True)  # e.g., "1000", "2100"
    name = Column(String(200), nullable=False)
    category = Column(String(50), nullable=False)  # chartered, company, employee, freelancer
    account_type = Column(String(50), nullable=False)  # asset, liability, equity, revenue, expense
    parent_id = Column(BigInteger, ForeignKey("accounting_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    tier = Column(Integer, default=1, nullable=False)  # 1 (Category), 2 (Group), 3 (Ledger), 4 (Sub-ledger)
    balance = Column(Numeric(15, 2), default=0.00, nullable=False)
    currency = Column(String(10), default="INR", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    parent = relationship("Account", remote_side=[id], backref="children")
    debit_entries = relationship("JournalEntryLine", foreign_keys="JournalEntryLine.debit_account_id", back_populates="debit_account")
    credit_entries = relationship("JournalEntryLine", foreign_keys="JournalEntryLine.credit_account_id", back_populates="credit_account")


class CompanyExpense(Base):
    __tablename__ = "accounting_expenses"

    id = Column(BigInteger, primary_key=True, index=True)
    expense_code = Column(String(50), unique=True, nullable=False, index=True)  # e.g., "EXP-2026-001"
    title = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False)  # rent, utilities, software, marketing, travel, office_supplies, legal, other
    vendor_name = Column(String(200), nullable=False)
    vendor_gstin = Column(String(20), nullable=True)
    vendor_pan = Column(String(15), nullable=True)
    invoice_number = Column(String(100), nullable=True)
    invoice_date = Column(Date, nullable=False)
    
    # Financial breakdown (Strict 2 decimal numeric)
    base_amount = Column(Numeric(12, 2), nullable=False)
    gst_rate = Column(Numeric(5, 2), default=0.00, nullable=False)  # 0, 5, 12, 18, 28
    gst_amount = Column(Numeric(12, 2), default=0.00, nullable=False)
    is_rcm = Column(Boolean, default=False, nullable=False)  # Reverse Charge Mechanism
    is_interstate = Column(Boolean, default=False, nullable=False)  # IGST vs CGST+SGST
    
    tds_section = Column(String(20), nullable=True)  # 194C, 194J, 194I, 194H
    tds_rate = Column(Numeric(5, 2), default=0.00, nullable=False)
    tds_amount = Column(Numeric(12, 2), default=0.00, nullable=False)
    
    total_amount = Column(Numeric(12, 2), nullable=False)  # Base + GST
    net_payable_amount = Column(Numeric(12, 2), nullable=False)  # Base + GST - TDS
    
    payment_status = Column(String(50), default="pending", nullable=False)  # pending, approved, paid, cancelled
    payment_mode = Column(String(50), default="bank_transfer", nullable=True)  # bank_transfer, upi, corporate_card, cash, cheque
    payment_date = Column(Date, nullable=True)
    payment_reference = Column(String(100), nullable=True)  # UTR / Transaction No
    receipt_url = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)

    created_by_id = Column(BigInteger, ForeignKey("employees.id"), nullable=True)
    approved_by_id = Column(BigInteger, ForeignKey("employees.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    created_by = relationship("Employee", foreign_keys=[created_by_id])
    approved_by = relationship("Employee", foreign_keys=[approved_by_id])


class FreelancerContractor(Base):
    __tablename__ = "accounting_freelancer_contractors"

    id = Column(BigInteger, primary_key=True, index=True)
    freelancer_code = Column(String(50), unique=True, nullable=False, index=True)  # e.g., "FL-001"
    name = Column(String(200), nullable=False)
    email = Column(String(150), nullable=False)
    phone = Column(String(20), nullable=False)
    pan_number = Column(String(15), nullable=False)
    gstin = Column(String(20), nullable=True)
    service_type = Column(String(100), nullable=False)  # Development, Design, Content, Marketing, QA
    tds_applicable_section = Column(String(20), default="194J", nullable=False)
    tds_default_rate = Column(Numeric(5, 2), default=10.00, nullable=False)
    
    bank_name = Column(String(100), nullable=True)
    bank_account_number = Column(String(50), nullable=True)
    bank_ifsc_code = Column(String(20), nullable=True)
    bank_beneficiary_name = Column(String(150), nullable=True)
    
    status = Column(String(50), default="active", nullable=False)  # active, inactive, terminated
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    invoices = relationship("FreelancerInvoice", back_populates="contractor", cascade="all, delete-orphan")


class FreelancerInvoice(Base):
    __tablename__ = "accounting_freelancer_invoices"

    id = Column(BigInteger, primary_key=True, index=True)
    contractor_id = Column(BigInteger, ForeignKey("accounting_freelancer_contractors.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_number = Column(String(100), nullable=False, index=True)
    invoice_date = Column(Date, nullable=False)
    description = Column(Text, nullable=False)
    period_month = Column(String(20), nullable=False)  # e.g., "2026-09"
    
    gross_amount = Column(Numeric(12, 2), nullable=False)
    gst_rate = Column(Numeric(5, 2), default=0.00, nullable=False)
    gst_amount = Column(Numeric(12, 2), default=0.00, nullable=False)
    tds_section = Column(String(20), default="194J", nullable=False)
    tds_rate = Column(Numeric(5, 2), default=10.00, nullable=False)
    tds_amount = Column(Numeric(12, 2), default=0.00, nullable=False)
    net_payable_amount = Column(Numeric(12, 2), nullable=False)
    
    status = Column(String(50), default="pending", nullable=False)  # pending, approved, paid, cancelled
    payment_mode = Column(String(50), default="bank_transfer", nullable=True)
    payment_date = Column(Date, nullable=True)
    payment_reference = Column(String(100), nullable=True)  # UTR / Ref
    invoice_document_url = Column(String(500), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    contractor = relationship("FreelancerContractor", back_populates="invoices")


class PayrollBatch(Base):
    __tablename__ = "accounting_payroll_batches"

    id = Column(BigInteger, primary_key=True, index=True)
    batch_code = Column(String(50), unique=True, nullable=False, index=True)  # e.g., "PAY-2026-09"
    month_year = Column(String(20), nullable=False, index=True)  # "2026-09"
    total_employees = Column(Integer, default=0, nullable=False)
    total_gross = Column(Numeric(15, 2), default=0.00, nullable=False)
    total_pf_deduction = Column(Numeric(15, 2), default=0.00, nullable=False)
    total_esi_deduction = Column(Numeric(15, 2), default=0.00, nullable=False)
    total_tds_deduction = Column(Numeric(15, 2), default=0.00, nullable=False)
    total_net_disbursed = Column(Numeric(15, 2), default=0.00, nullable=False)
    
    status = Column(String(50), default="draft", nullable=False)  # draft, approved, processed, disbursed
    disbursement_date = Column(Date, nullable=True)
    processed_by_id = Column(BigInteger, ForeignKey("employees.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    processed_by = relationship("Employee", foreign_keys=[processed_by_id])
    records = relationship("PayrollEmployeeRecord", back_populates="batch", cascade="all, delete-orphan")


class PayrollEmployeeRecord(Base):
    __tablename__ = "accounting_payroll_records"

    id = Column(BigInteger, primary_key=True, index=True)
    batch_id = Column(BigInteger, ForeignKey("accounting_payroll_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id = Column(BigInteger, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    
    basic_salary = Column(Numeric(12, 2), nullable=False)
    hra = Column(Numeric(12, 2), default=0.00, nullable=False)
    special_allowance = Column(Numeric(12, 2), default=0.00, nullable=False)
    gross_salary = Column(Numeric(12, 2), nullable=False)
    
    pf_employee = Column(Numeric(12, 2), default=0.00, nullable=False)
    pf_employer = Column(Numeric(12, 2), default=0.00, nullable=False)
    esi_employee = Column(Numeric(12, 2), default=0.00, nullable=False)
    esi_employer = Column(Numeric(12, 2), default=0.00, nullable=False)
    tds_withheld = Column(Numeric(12, 2), default=0.00, nullable=False)
    other_deductions = Column(Numeric(12, 2), default=0.00, nullable=False)
    total_deductions = Column(Numeric(12, 2), default=0.00, nullable=False)
    
    net_salary = Column(Numeric(12, 2), nullable=False)
    payment_status = Column(String(50), default="pending", nullable=False)  # pending, paid
    payment_date = Column(Date, nullable=True)
    payment_reference = Column(String(100), nullable=True)
    payslip_pdf_url = Column(String(500), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    batch = relationship("PayrollBatch", back_populates="records")
    employee = relationship("Employee", foreign_keys=[employee_id])


class JournalEntry(Base):
    __tablename__ = "accounting_journal_entries"

    id = Column(BigInteger, primary_key=True, index=True)
    voucher_number = Column(String(50), unique=True, nullable=False, index=True)  # e.g., "JV-2026-0001"
    entry_date = Column(Date, nullable=False, index=True)
    voucher_type = Column(String(50), nullable=False)  # expense, payroll, freelancer_payment, tax_payment, manual_journal
    reference_id = Column(String(100), nullable=True)  # e.g., EXP-2026-001 or PAY-2026-09
    reference_type = Column(String(50), nullable=True)
    narration = Column(Text, nullable=False)
    
    total_debit = Column(Numeric(15, 2), nullable=False)
    total_credit = Column(Numeric(15, 2), nullable=False)
    status = Column(String(50), default="posted", nullable=False)  # draft, posted, voided
    
    created_by_id = Column(BigInteger, ForeignKey("employees.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    created_by = relationship("Employee", foreign_keys=[created_by_id])
    lines = relationship("JournalEntryLine", back_populates="journal_entry", cascade="all, delete-orphan")


class JournalEntryLine(Base):
    __tablename__ = "accounting_journal_lines"

    id = Column(BigInteger, primary_key=True, index=True)
    journal_entry_id = Column(BigInteger, ForeignKey("accounting_journal_entries.id", ondelete="CASCADE"), nullable=False, index=True)
    debit_account_id = Column(BigInteger, ForeignKey("accounting_accounts.id"), nullable=True, index=True)
    credit_account_id = Column(BigInteger, ForeignKey("accounting_accounts.id"), nullable=True, index=True)
    amount = Column(Numeric(15, 2), nullable=False)
    description = Column(String(255), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    journal_entry = relationship("JournalEntry", back_populates="lines")
    debit_account = relationship("Account", foreign_keys=[debit_account_id], back_populates="debit_entries")
    credit_account = relationship("Account", foreign_keys=[credit_account_id], back_populates="credit_entries")


class GstFilingRecord(Base):
    __tablename__ = "accounting_gst_filings"

    id = Column(BigInteger, primary_key=True, index=True)
    filing_period = Column(String(20), nullable=False, index=True)  # e.g., "2026-09"
    return_type = Column(String(50), nullable=False)  # GSTR-1, GSTR-3B, GSTR-9
    
    taxable_sales = Column(Numeric(15, 2), default=0.00, nullable=False)
    output_cgst = Column(Numeric(12, 2), default=0.00, nullable=False)
    output_sgst = Column(Numeric(12, 2), default=0.00, nullable=False)
    output_igst = Column(Numeric(12, 2), default=0.00, nullable=False)
    total_output_tax = Column(Numeric(15, 2), default=0.00, nullable=False)
    
    eligible_itc_cgst = Column(Numeric(12, 2), default=0.00, nullable=False)
    eligible_itc_sgst = Column(Numeric(12, 2), default=0.00, nullable=False)
    eligible_itc_igst = Column(Numeric(12, 2), default=0.00, nullable=False)
    total_itc_claimed = Column(Numeric(15, 2), default=0.00, nullable=False)
    
    net_tax_payable = Column(Numeric(15, 2), default=0.00, nullable=False)
    tax_paid_cash = Column(Numeric(15, 2), default=0.00, nullable=False)
    challan_reference = Column(String(100), nullable=True)
    filing_arn = Column(String(100), nullable=True)
    filing_date = Column(Date, nullable=True)
    status = Column(String(50), default="ready_to_file", nullable=False)  # draft, ready_to_file, filed, overdue
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class TdsChallanRecord(Base):
    __tablename__ = "accounting_tds_challans"

    id = Column(BigInteger, primary_key=True, index=True)
    challan_number = Column(String(50), unique=True, nullable=False, index=True)
    bsr_code = Column(String(20), nullable=False)
    deposit_date = Column(Date, nullable=False)
    section = Column(String(20), nullable=False)  # 192 (Salary), 194C, 194J, 194I
    financial_year = Column(String(20), nullable=False)  # "2026-27"
    quarter = Column(String(10), nullable=False)  # Q1, Q2, Q3, Q4
    
    tax_amount = Column(Numeric(12, 2), nullable=False)
    surcharge = Column(Numeric(12, 2), default=0.00, nullable=False)
    cess = Column(Numeric(12, 2), default=0.00, nullable=False)
    interest_fee = Column(Numeric(12, 2), default=0.00, nullable=False)
    total_deposit = Column(Numeric(12, 2), nullable=False)
    
    cin_number = Column(String(50), nullable=True)
    bank_reference = Column(String(100), nullable=True)
    status = Column(String(50), default="deposited", nullable=False)  # pending, deposited, reconciled
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
