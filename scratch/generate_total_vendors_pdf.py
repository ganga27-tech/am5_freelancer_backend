import os
import json
import re
from datetime import datetime
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
import pypdfium2 as pdfium

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pages = []

    def showPage(self):
        self.pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        page_count = len(self.pages)
        for page in self.pages:
            self.__dict__.update(page)
            self.draw_decorations(page_count)
            super().showPage()
        super().save()

    def draw_decorations(self, page_count):
        self.saveState()
        
        # Running Header (pages 2+)
        if self._pageNumber > 1:
            self.setFont("Helvetica-Bold", 8)
            self.setFillColor(colors.HexColor("#1E293B"))
            self.drawString(24, 586, "AM5ROYAL  |  TOTAL VENDORS ONBOARDING & GEOGRAPHIC STEPS REPORT")
            self.setFont("Helvetica", 8)
            self.setFillColor(colors.HexColor("#64748B"))
            self.drawRightString(792 - 24, 586, "CONFIDENTIAL & PROPRIETARY")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(24, 580, 792 - 24, 580)

        # Running Footer (all pages)
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        gen_time = datetime.now().strftime("%B %d, %Y at %I:%M %p")
        self.drawString(24, 18, f"Generated: {gen_time}  |  AM5Royal Operations & Vendor Management System")
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(792 - 24, 18, page_text)
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(24, 28, 792 - 24, 28)

        self.restoreState()

def sanitize_text(val):
    if val is None:
        return "N/A"
    s = str(val).strip()
    if not s or s.lower() in ('none', 'null'):
        return "N/A"
    # Normalize common state names
    s_norm = s.strip()
    if s_norm.lower() in ('andhra pradesh', 'andhrapradesh', 'andra pradesh', 'andhraprabdesh', 'andhra pradesdh', 'andhraparadesh', 'andrapradesh'):
        s_norm = 'Andhra Pradesh'
    elif s_norm.lower() in ('telangana', 'telanga'):
        s_norm = 'Telangana'
    elif s_norm.lower() in ('maharashtra', 'maharastra', 'maharstra'):
        s_norm = 'Maharashtra'
    elif s_norm.lower() in ('uttar pradesh', 'uttara pradesh', 'uttar praesh', 'uttara  pradesh'):
        s_norm = 'Uttar Pradesh'
    elif s_norm.lower() in ('tamil nadu', 'tamilanadu'):
        s_norm = 'Tamil Nadu'
    elif s_norm.lower() in ('gujarat', 'gujatat'):
        s_norm = 'Gujarat'
    elif s_norm.lower() in ('chattisgarh', 'chhatisgarh', 'chhatisgargh'):
        s_norm = 'Chhattisgarh'
    elif s_norm.lower() in ('jharkhand', 'jharkand', 'jarkhand'):
        s_norm = 'Jharkhand'
    elif s_norm.lower() in ('uttarakhand', 'uttarkhand'):
        s_norm = 'Uttarakhand'
    elif s_norm.lower() == 'vijayawada':
        s_norm = 'Andhra Pradesh'

    s = s_norm
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r'[^\x00-\x7F]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s if s else "N/A"

def determine_step(r):
    has_sub = r.get('latest_sub_status') == 'active' or (r.get('latest_sub_plan') is not None)
    has_slots = (r.get('slots_count') or 0) > 0
    has_cat = (r.get('subcategories_count') or 0) > 0 or (r.get('services_count') or 0) > 0
    has_reg = bool((r.get('first_name') and r.get('first_name').strip()) or 
                   (r.get('business_name') and r.get('business_name').strip()) or 
                   r.get('vendor_id'))
    otp = r.get('otp_verified')

    if has_sub:
        return 'Payment / Subscribed', 1, "#166534"
    elif has_slots:
        return 'Slot Booking', 2, "#854D0E"
    elif has_cat:
        return 'Subcategory & Services', 3, "#1E40AF"
    elif has_reg:
        return 'Profile Registration', 4, "#6B21A8"
    elif otp:
        return 'OTP Verified Only', 5, "#991B1B"
    else:
        return 'OTP Pending', 6, "#475569"

def generate_pdf():
    json_path = 'd:/fb/all_vendors_steps.json'
    with open(json_path, 'r', encoding='utf-8') as f:
        vendors = json.load(f)

    total_vendors = len(vendors)
    print(f"Loaded {total_vendors} vendors from {json_path}")

    processed = []
    step_counts = {
        'Payment / Subscribed': 0,
        'Slot Booking': 0,
        'Subcategory & Services': 0,
        'Profile Registration': 0,
        'OTP Verified Only': 0,
        'OTP Pending': 0
    }
    state_counts = {}

    for v in vendors:
        step_name, order, color_code = determine_step(v)
        step_counts[step_name] = step_counts.get(step_name, 0) + 1
        
        st = sanitize_text(v.get('state'))
        if st != 'N/A':
            state_counts[st] = state_counts.get(st, 0) + 1
        else:
            state_counts['Incomplete / Not Entered'] = state_counts.get('Incomplete / Not Entered', 0) + 1

        first_n = (v.get('first_name') or '').strip()
        last_n = (v.get('last_name') or '').strip()
        full_name = f"{first_n} {last_n}".strip() if (first_n or last_n) else "N/A"

        b_name = (v.get('business_name') or '').strip() or "N/A"
        mobile = (v.get('vendor_mobile') or v.get('user_mobile') or 'N/A').strip()
        
        district = sanitize_text(v.get('district'))
        city = sanitize_text(v.get('city'))
        pincode = sanitize_text(v.get('pincode'))

        processed.append({
            'user_id': v.get('user_id'),
            'vendor_id': v.get('vendor_id') or "N/A",
            'name': sanitize_text(full_name),
            'business_name': sanitize_text(b_name),
            'mobile': sanitize_text(mobile),
            'state': st,
            'district': district,
            'city': city,
            'pincode': pincode,
            'step': step_name,
            'step_order': order,
            'color': color_code,
            'services_count': v.get('services_count') or 0,
            'slots_count': v.get('slots_count') or 0,
            'sub_plan': sanitize_text(v.get('latest_sub_plan'))
        })

    # Sort vendors by Step order, then State, then District, then User ID
    processed.sort(key=lambda x: (x['step_order'], x['state'] == 'Incomplete / Not Entered', x['state'], x['district'], x['user_id']))

    # Setup Document
    pdf_path = "d:/fb/total_vendors_steps_report.pdf"
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=landscape(letter),
        leftMargin=24,
        rightMargin=24,
        topMargin=32,
        bottomMargin=32
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=17,
        leading=21,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=3
    )

    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#475569"),
        spaceAfter=12
    )

    section_title = ParagraphStyle(
        'SecTitle',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#1E3A8A"),
        spaceBefore=8,
        spaceAfter=5
    )

    th_style = ParagraphStyle(
        'TableHeader',
        fontName='Helvetica-Bold',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.white
    )

    cell_style = ParagraphStyle(
        'TableCell',
        fontName='Helvetica',
        fontSize=7,
        leading=8.5,
        textColor=colors.HexColor("#1E293B")
    )

    cell_bold = ParagraphStyle(
        'TableCellBold',
        fontName='Helvetica-Bold',
        fontSize=7,
        leading=8.5,
        textColor=colors.HexColor("#0F172A")
    )

    story = []

    # Title & Metadata
    story.append(Paragraph("AM5ROYAL - TOTAL VENDORS ONBOARDING & GEOGRAPHIC STEPS REPORT", title_style))
    story.append(Paragraph(
        f"Comprehensive audit of all <b>{total_vendors} registered vendor accounts</b>, detailing their current stage in the onboarding funnel, geographic location (State & District), and profile status. Data synced from production database.",
        subtitle_style
    ))

    # Funnel Table
    funnel_data = [
        [
            Paragraph("<b>Onboarding Funnel Step</b>", th_style),
            Paragraph("<b>Stage Description</b>", th_style),
            Paragraph("<b>Vendors</b>", th_style),
            Paragraph("<b>Share</b>", th_style)
        ]
    ]

    funnel_configs = [
        ("Payment / Subscribed", "Active subscription plan / Paid onboarding", "#166534"),
        ("Slot Booking", "Service slots & schedule configured, payment pending", "#854D0E"),
        ("Subcategory & Services", "Services/subcategories chosen, slots pending", "#1E40AF"),
        ("Profile Registration", "Basic profile details entered, services pending", "#6B21A8"),
        ("OTP Verified Only", "Phone verified, profile details pending", "#991B1B"),
        ("OTP Pending", "Signup initiated, OTP verification incomplete", "#475569")
    ]

    for step_title, desc, clr in funnel_configs:
        cnt = step_counts.get(step_title, 0)
        pct = f"{(cnt / total_vendors * 100):.1f}%"
        step_p = Paragraph(f"<b><font color='{clr}'>{step_title}</font></b>", cell_style)
        desc_p = Paragraph(desc, cell_style)
        cnt_p = Paragraph(f"<b>{cnt}</b>", cell_bold)
        pct_p = Paragraph(pct, cell_style)
        funnel_data.append([step_p, desc_p, cnt_p, pct_p])

    # Total Row
    funnel_data.append([
        Paragraph("<b>TOTAL VENDORS</b>", cell_bold),
        Paragraph("<b>All registered vendor users</b>", cell_bold),
        Paragraph(f"<b>{total_vendors}</b>", cell_bold),
        Paragraph("<b>100.0%</b>", cell_bold)
    ])

    funnel_table = Table(funnel_data, colWidths=[115, 195, 45, 45])
    funnel_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#E2E8F0")),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
    ]))

    # Top States Table (Top 5 actual states + Incomplete)
    known_states = {k: v for k, v in state_counts.items() if k != 'Incomplete / Not Entered'}
    sorted_known = sorted(known_states.items(), key=lambda x: x[1], reverse=True)[:5]
    
    top_states_data = [
        [
            Paragraph("<b>Top State / Territory</b>", th_style),
            Paragraph("<b>Vendors</b>", th_style),
            Paragraph("<b>Share</b>", th_style)
        ]
    ]
    for st_name, st_cnt in sorted_known:
        pct = f"{(st_cnt / total_vendors * 100):.1f}%"
        top_states_data.append([
            Paragraph(f"<b>{st_name}</b>", cell_style),
            Paragraph(f"<b>{st_cnt}</b>", cell_bold),
            Paragraph(pct, cell_style)
        ])

    # Add other states and incomplete
    incomp_cnt = state_counts.get('Incomplete / Not Entered', 0)
    other_cnt = total_vendors - sum(x[1] for x in sorted_known) - incomp_cnt
    if other_cnt > 0:
        top_states_data.append([
            Paragraph("Other States (Combined)", cell_style),
            Paragraph(str(other_cnt), cell_style),
            Paragraph(f"{(other_cnt / total_vendors * 100):.1f}%", cell_style)
        ])
    top_states_data.append([
        Paragraph("Profile Incomplete / Pending Form", cell_style),
        Paragraph(str(incomp_cnt), cell_style),
        Paragraph(f"{(incomp_cnt / total_vendors * 100):.1f}%", cell_style)
    ])

    top_states_table = Table(top_states_data, colWidths=[185, 48, 48])
    top_states_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#0F766E")),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
    ]))

    summary_composite = Table([[funnel_table, top_states_table]], colWidths=[415, 295])
    summary_composite.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))

    story.append(summary_composite)
    story.append(Spacer(1, 10))

    # Main Vendors Table
    story.append(Paragraph("Master Vendor Register with Onboarding Steps, State & District", section_title))

    # Total width = 744 pt
    col_widths = [30, 52, 92, 105, 65, 80, 82, 75, 100, 63]

    master_headers = [
        Paragraph("<b>S.No</b>", th_style),
        Paragraph("<b>UID / VID</b>", th_style),
        Paragraph("<b>Vendor Name</b>", th_style),
        Paragraph("<b>Business Name</b>", th_style),
        Paragraph("<b>Mobile</b>", th_style),
        Paragraph("<b>State</b>", th_style),
        Paragraph("<b>District</b>", th_style),
        Paragraph("<b>City</b>", th_style),
        Paragraph("<b>Current Step</b>", th_style),
        Paragraph("<b>Details</b>", th_style)
    ]

    table_rows = [master_headers]

    for idx, item in enumerate(processed, start=1):
        uid_vid = f"U#{item['user_id']}<br/>V#{item['vendor_id']}" if item['vendor_id'] != 'N/A' else f"U#{item['user_id']}"
        step_html = f"<b><font color='{item['color']}'>{item['step']}</font></b>"
        
        if item['step'] == 'Payment / Subscribed':
            details_html = f"Plan: {item['sub_plan']}" if item['sub_plan'] != 'N/A' else "Active Sub"
        elif item['step'] == 'Slot Booking':
            details_html = f"{item['slots_count']} Slots Set"
        elif item['step'] == 'Subcategory & Services':
            details_html = f"{item['services_count']} Services"
        elif item['step'] == 'Profile Registration':
            details_html = "Profile Saved"
        else:
            details_html = "Pending Form"

        table_rows.append([
            Paragraph(str(idx), cell_style),
            Paragraph(uid_vid, cell_style),
            Paragraph(item['name'], cell_style),
            Paragraph(item['business_name'], cell_style),
            Paragraph(item['mobile'], cell_style),
            Paragraph(item['state'], cell_style),
            Paragraph(item['district'], cell_style),
            Paragraph(item['city'], cell_style),
            Paragraph(step_html, cell_style),
            Paragraph(details_html, cell_style)
        ])

    master_table = Table(table_rows, colWidths=col_widths, repeatRows=1)
    
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1E293B")),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, 0), 4),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
        ('TOPPADDING', (0, 1), (-1, -1), 2.2),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 2.2),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
    ])

    for i in range(1, len(table_rows)):
        if i % 2 == 0:
            table_style.add('BACKGROUND', (0, i), (-1, i), colors.HexColor("#F8FAFC"))

    master_table.setStyle(table_style)
    story.append(master_table)

    print("Building refined PDF document...")
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"Successfully generated PDF: {pdf_path}")

    # Re-render page 1 to verify
    pdf = pdfium.PdfDocument(pdf_path)
    page1 = pdf[0]
    img1 = page1.render(scale=2).to_pil()
    img1.save('d:/fb/am5-backend/scratch/page1_refined.png')
    print("Rendered page1_refined.png successfully.")

if __name__ == '__main__':
    generate_pdf()
