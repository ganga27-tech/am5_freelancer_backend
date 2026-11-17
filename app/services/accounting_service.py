from datetime import date, datetime
from typing import List, Dict, Any, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.orm import selectinload

from app.models.accounting import (
    Account,
    CompanyExpense,
    FreelancerContractor,
    FreelancerInvoice,
    PayrollBatch,
    PayrollEmployeeRecord,
    JournalEntry,
    JournalEntryLine,
    GstFilingRecord,
    TdsChallanRecord,
)
from app.models.employee import Employee


def round_cur(val: float | Decimal) -> float:
    d = Decimal(str(val))
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class AccountingCalculationEngine:
    """Production-grade calculation engine for Indian GST, TDS, and Payroll statutory deductions."""

    @staticmethod
    def calculate_expense_taxes(
        base_amount: float,
        gst_rate: float = 0.0,
        is_rcm: bool = False,
        tds_rate: float = 0.0,
    ) -> Dict[str, float]:
        base = round_cur(base_amount)
        gst_pct = Decimal(str(gst_rate)) / Decimal("100")
        tds_pct = Decimal(str(tds_rate)) / Decimal("100")
        
        gst_amount = round_cur(Decimal(str(base)) * gst_pct)
        tds_amount = round_cur(Decimal(str(base)) * tds_pct)
        
        # If RCM (Reverse Charge Mechanism), GST is paid directly by company to government,
        # not paid to the vendor.
        total_invoice = round_cur(base + (0.0 if is_rcm else gst_amount))
        net_payable = round_cur(total_invoice - tds_amount)
        
        return {
            "base_amount": base,
            "gst_rate": gst_rate,
            "gst_amount": gst_amount,
            "tds_rate": tds_rate,
            "tds_amount": tds_amount,
            "total_amount": round_cur(base + gst_amount),
            "net_payable_amount": max(0.0, net_payable),
        }

    @staticmethod
    def calculate_payroll_deductions(
        basic: float,
        hra: float = 0.0,
        special_allowance: float = 0.0,
        custom_tds: Optional[float] = None,
        other_deductions: float = 0.0,
    ) -> Dict[str, float]:
        basic_dec = Decimal(str(round_cur(basic)))
        hra_dec = Decimal(str(round_cur(hra)))
        sa_dec = Decimal(str(round_cur(special_allowance)))
        
        gross = basic_dec + hra_dec + sa_dec
        gross_fl = round_cur(gross)
        
        # 1. Provident Fund (EPF): 12% of basic (capped at ceiling of ₹15,000 basic -> ₹1,800 or actual)
        pf_employee = round_cur(min(basic_dec, Decimal("15000")) * Decimal("0.12"))
        pf_employer = pf_employee
        
        # 2. ESI: 0.75% of Gross if Gross <= ₹21,000 / month
        if gross <= Decimal("21000"):
            esi_employee = round_cur(gross * Decimal("0.0075"))
            esi_employer = round_cur(gross * Decimal("0.0325"))
        else:
            esi_employee = 0.0
            esi_employer = 0.0
            
        # 3. TDS: either custom provided or calculated on annual slab
        if custom_tds is not None and custom_tds >= 0:
            tds_val = round_cur(custom_tds)
        else:
            annual_gross = float(gross) * 12
            if annual_gross > 1200000:
                tds_val = round_cur(float(gross) * 0.15)
            elif annual_gross > 700000:
                tds_val = round_cur(float(gross) * 0.05)
            else:
                tds_val = 0.0
                
        other_ded_fl = round_cur(other_deductions)
        total_deductions = round_cur(pf_employee + esi_employee + tds_val + other_ded_fl)
        net_salary = round_cur(gross_fl - total_deductions)
        
        return {
            "basic_salary": round_cur(basic_dec),
            "hra": round_cur(hra_dec),
            "special_allowance": round_cur(sa_dec),
            "gross_salary": gross_fl,
            "pf_employee": pf_employee,
            "pf_employer": pf_employer,
            "esi_employee": esi_employee,
            "esi_employer": esi_employer,
            "tds_withheld": tds_val,
            "other_deductions": other_ded_fl,
            "total_deductions": total_deductions,
            "net_salary": max(0.0, net_salary),
        }


class AccountingService:
    def __init__(self):
        self.calc = AccountingCalculationEngine()

    async def get_or_create_account(
        self,
        db: AsyncSession,
        code: str,
        name: str,
        category: str,
        account_type: str,
        tier: int = 3,
        parent_id: Optional[int] = None
    ) -> Account:
        res = await db.execute(select(Account).where(Account.code == code))
        account = res.scalar_one_or_none()
        if not account:
            account = Account(
                code=code,
                name=name,
                category=category,
                account_type=account_type,
                tier=tier,
                parent_id=parent_id,
                balance=0.00,
                is_active=True,
            )
            db.add(account)
            await db.flush()
        return account

    async def create_journal_voucher(
        self,
        db: AsyncSession,
        voucher_type: str,
        narration: str,
        lines_data: List[Dict[str, Any]],
        entry_date: Optional[date] = None,
        reference_id: Optional[str] = None,
        created_by_id: Optional[int] = None,
    ) -> JournalEntry:
        """Create and automatically post a balanced double-entry voucher."""
        if not entry_date:
            entry_date = date.today()
            
        total_debit = Decimal("0.00")
        total_credit = Decimal("0.00")
        
        for line in lines_data:
            amt = Decimal(str(round_cur(line["amount"])))
            if line.get("debit_account_id"):
                total_debit += amt
            elif line.get("credit_account_id"):
                total_credit += amt
            else:
                raise ValueError("Journal line must contain debit_account_id or credit_account_id")
                
        if round(total_debit, 2) != round(total_credit, 2):
            raise ValueError(f"Unbalanced Journal Voucher: Total Debits (₹{total_debit}) != Total Credits (₹{total_credit})")

        # Generate unique voucher number
        year_prefix = entry_date.strftime("%Y%m")
        count_query = select(func.count(JournalEntry.id))
        count_res = await db.execute(count_query)
        v_seq = (count_res.scalar() or 0) + 1
        voucher_number = f"JV-{year_prefix}-{v_seq:04d}"

        entry = JournalEntry(
            voucher_number=voucher_number,
            entry_date=entry_date,
            voucher_type=voucher_type,
            reference_id=reference_id,
            narration=narration,
            total_debit=round_cur(total_debit),
            total_credit=round_cur(total_credit),
            status="posted",
            created_by_id=created_by_id,
        )
        db.add(entry)
        await db.flush()

        for line in lines_data:
            amt = round_cur(line["amount"])
            db_line = JournalEntryLine(
                journal_entry_id=entry.id,
                debit_account_id=line.get("debit_account_id"),
                credit_account_id=line.get("credit_account_id"),
                amount=amt,
                description=line.get("description"),
            )
            db.add(db_line)

            # Update account balance
            if line.get("debit_account_id"):
                acc_res = await db.execute(select(Account).where(Account.id == line["debit_account_id"]))
                acc = acc_res.scalar_one_or_none()
                if acc:
                    # For asset & expense: Debit increases balance
                    if acc.account_type in ["asset", "expense"]:
                        acc.balance = float(acc.balance) + amt
                    else:
                        acc.balance = float(acc.balance) - amt
            
            if line.get("credit_account_id"):
                acc_res = await db.execute(select(Account).where(Account.id == line["credit_account_id"]))
                acc = acc_res.scalar_one_or_none()
                if acc:
                    # For liability, equity, revenue: Credit increases balance
                    if acc.account_type in ["liability", "equity", "revenue"]:
                        acc.balance = float(acc.balance) + amt
                    else:
                        acc.balance = float(acc.balance) - amt

        await db.flush()
        return entry

    async def seed_default_chart_of_accounts(self, db: AsyncSession) -> int:
        """Prepopulates AM5 Royal statutory 4-tier Chart of Accounts."""
        default_accounts = [
            # Tier 1 - Primary Categories
            {"code": "1000", "name": "Statutory & Chartered Accounts (Assets/Liabilities)", "category": "chartered", "account_type": "asset", "tier": 1},
            {"code": "2000", "name": "Company Operational Accounts", "category": "company", "account_type": "expense", "tier": 1},
            {"code": "3000", "name": "Employee Salary & Benefits Accounts", "category": "employee", "account_type": "expense", "tier": 1},
            {"code": "4000", "name": "Freelancer & Contractor Accounts", "category": "freelancer", "account_type": "expense", "tier": 1},

            # Tier 2 & 3 - Liquid Assets & Statutory Taxes
            {"code": "1100", "name": "Cash & Bank Balances", "category": "chartered", "account_type": "asset", "tier": 2, "parent_code": "1000"},
            {"code": "1110", "name": "HDFC Bank Operating Current A/c", "category": "chartered", "account_type": "asset", "tier": 3, "parent_code": "1100", "balance": 4850000.00},
            {"code": "1120", "name": "ICICI Bank Tax Reserve A/c", "category": "chartered", "account_type": "asset", "tier": 3, "parent_code": "1100", "balance": 1250000.00},
            {"code": "1130", "name": "Company Petty Cash", "category": "chartered", "account_type": "asset", "tier": 3, "parent_code": "1100", "balance": 75000.00},

            {"code": "1200", "name": "Statutory Tax Receivables & ITC", "category": "chartered", "account_type": "asset", "tier": 2, "parent_code": "1000"},
            {"code": "1210", "name": "GST Input Tax Credit (CGST/SGST/IGST)", "category": "chartered", "account_type": "asset", "tier": 3, "parent_code": "1200", "balance": 342000.00},
            {"code": "1220", "name": "TDS Receivable (Advance Tax)", "category": "chartered", "account_type": "asset", "tier": 3, "parent_code": "1200", "balance": 185000.00},

            {"code": "1300", "name": "Statutory Tax Payables (Liabilities)", "category": "chartered", "account_type": "liability", "tier": 2, "parent_code": "1000"},
            {"code": "1310", "name": "GST Output Tax Payable", "category": "chartered", "account_type": "liability", "tier": 3, "parent_code": "1300", "balance": 486000.00},
            {"code": "1320", "name": "TDS Payable (Sec 192, 194C, 194J, 194I)", "category": "chartered", "account_type": "liability", "tier": 3, "parent_code": "1300", "balance": 194500.00},
            {"code": "1330", "name": "EPF & ESI Payable", "category": "chartered", "account_type": "liability", "tier": 3, "parent_code": "1300", "balance": 88400.00},

            # Tier 2 & 3 - Operational Expenses
            {"code": "2100", "name": "Office Rent & Facility Expenses", "category": "company", "account_type": "expense", "tier": 2, "parent_code": "2000"},
            {"code": "2110", "name": "Headquarters Lease Rent", "category": "company", "account_type": "expense", "tier": 3, "parent_code": "2100"},
            {"code": "2120", "name": "Electricity, Internet & Utilities", "category": "company", "account_type": "expense", "tier": 3, "parent_code": "2100"},

            {"code": "2200", "name": "Technology, Cloud & Software Subscriptions", "category": "company", "account_type": "expense", "tier": 2, "parent_code": "2000"},
            {"code": "2210", "name": "AWS Cloud & Infrastructure", "category": "company", "account_type": "expense", "tier": 3, "parent_code": "2200"},
            {"code": "2220", "name": "SaaS & Productivity Licenses", "category": "company", "account_type": "expense", "tier": 3, "parent_code": "2200"},

            {"code": "2300", "name": "Marketing, PR & Advertising", "category": "company", "account_type": "expense", "tier": 2, "parent_code": "2000"},
            {"code": "2310", "name": "Digital Ads (Meta / Google)", "category": "company", "account_type": "expense", "tier": 3, "parent_code": "2300"},
            {"code": "2320", "name": "Print & Outdoor Collateral", "category": "company", "account_type": "expense", "tier": 3, "parent_code": "2300"},

            # Tier 2 & 3 - Payroll Accounts
            {"code": "3100", "name": "Employee Base Salaries & Allowances", "category": "employee", "account_type": "expense", "tier": 2, "parent_code": "3000"},
            {"code": "3110", "name": "Executive & Engineering Salaries", "category": "employee", "account_type": "expense", "tier": 3, "parent_code": "3100"},
            {"code": "3120", "name": "Operations & Support Salaries", "category": "employee", "account_type": "expense", "tier": 3, "parent_code": "3100"},
            {"code": "3200", "name": "Employer Statutory Contributions (PF/ESI)", "category": "employee", "account_type": "expense", "tier": 2, "parent_code": "3000"},

            # Tier 2 & 3 - Freelancer Accounts
            {"code": "4100", "name": "Contract Technical & Engineering Services", "category": "freelancer", "account_type": "expense", "tier": 2, "parent_code": "4000"},
            {"code": "4200", "name": "Contract Creative & Content Services", "category": "freelancer", "account_type": "expense", "tier": 2, "parent_code": "4000"},
        ]

        count = 0
        code_to_id = {}
        for item in default_accounts:
            res = await db.execute(select(Account).where(Account.code == item["code"]))
            existing = res.scalar_one_or_none()
            parent_id = code_to_id.get(item.get("parent_code"))
            
            if not existing:
                acc = Account(
                    code=item["code"],
                    name=item["name"],
                    category=item["category"],
                    account_type=item["account_type"],
                    tier=item["tier"],
                    parent_id=parent_id,
                    balance=item.get("balance", 0.00),
                    is_active=True,
                )
                db.add(acc)
                await db.flush()
                code_to_id[item["code"]] = acc.id
                count += 1
            else:
                code_to_id[item["code"]] = existing.id

        await db.commit()
        return count


accounting_service = AccountingService()
