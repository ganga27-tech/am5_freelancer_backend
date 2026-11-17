import os
import sys
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, KeepTogether, PageBreak, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

# Output PDF path
PDF_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "AM5_Backend_Architecture_Design.pdf"))
DIAGRAM_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "diagrams"))
os.makedirs(DIAGRAM_DIR, exist_ok=True)

# -------------------------------------------------------------
# Color Palette
# -------------------------------------------------------------
PRIMARY = colors.HexColor("#0F172A")    # Slate 900
SECONDARY = colors.HexColor("#1E3A8A")  # Blue 900
ACCENT = colors.HexColor("#2563EB")     # Blue 600
ACCENT_LIGHT = colors.HexColor("#DBEAFE") # Blue 100
TEXT_DARK = colors.HexColor("#1E293B")  # Slate 800
TEXT_MUTED = colors.HexColor("#64748B") # Slate 500
BG_LIGHT = colors.HexColor("#F8FAFC")   # Slate 50
BORDER_COLOR = colors.HexColor("#CBD5E1") # Slate 300
SUCCESS = colors.HexColor("#059669")    # Emerald 600

# -------------------------------------------------------------
# 1. Diagram Generators using PIL (High-Resolution 300 DPI)
# -------------------------------------------------------------
def get_font(size=14, bold=False):
    # Try Windows fonts
    font_paths = [
        r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibrib.ttf" if bold else r"C:\Windows\Fonts\calibri.ttf"
    ]
    for p in font_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

def draw_rounded_box(draw, box, radius=12, fill="#FFFFFF", outline="#CBD5E1", width=2):
    x0, y0, x1, y1 = box
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill, outline=outline, width=width)

def draw_arrow(draw, start, end, color="#2563EB", width=3, arrow_size=10):
    x0, y0 = start
    x1, y1 = end
    draw.line([x0, y0, x1, y1], fill=color, width=width)
    import math
    angle = math.atan2(y1 - y0, x1 - x0)
    # Arrow head
    p1 = (x1 - arrow_size * math.cos(angle - math.pi / 6), y1 - arrow_size * math.sin(angle - math.pi / 6))
    p2 = (x1 - arrow_size * math.cos(angle + math.pi / 6), y1 - arrow_size * math.sin(angle + math.pi / 6))
    draw.polygon([ (x1, y1), p1, p2 ], fill=color)

def generate_system_arch_diagram():
    # Dimensions
    W, H = 1600, 950
    img = Image.new("RGBA", (W, H), "#F8FAFC")
    draw = ImageDraw.Draw(img)

    title_font = get_font(26, bold=True)
    header_font = get_font(20, bold=True)
    box_title_font = get_font(18, bold=True)
    sub_font = get_font(14, bold=False)
    tag_font = get_font(13, bold=True)

    # 1. CLIENTS SECTION (Top Left to Right)
    draw_rounded_box(draw, (40, 40, 1560, 200), radius=16, fill="#EFF6FF", outline="#93C5FD", width=2)
    draw.text((60, 55), "CLIENT TIER (Multi-Platform Frontends)", fill="#1E3A8A", font=header_font)
    
    clients = [
        ("Vendor Mobile App", "Flutter (Android/iOS)", "#3B82F6", (80, 95, 480, 175)),
        ("Customer Mobile App", "Flutter (Android/iOS)", "#10B981", (540, 95, 940, 175)),
        ("Admin & Accounting Panels", "React / Vite / TypeScript", "#8B5CF6", (1000, 95, 1520, 175)),
    ]
    for name, sub, col, box in clients:
        draw_rounded_box(draw, box, radius=10, fill="#FFFFFF", outline=col, width=2)
        draw.text((box[0] + 20, box[1] + 16), name, fill="#0F172A", font=box_title_font)
        draw.text((box[0] + 20, box[1] + 45), sub, fill="#64748B", font=sub_font)

    # 2. EDGE / GATEWAY LAYER
    draw_rounded_box(draw, (40, 240, 1560, 360), radius=16, fill="#F1F5F9", outline="#CBD5E1", width=2)
    draw.text((60, 255), "EDGE & REVERSE PROXY LAYER (Hostinger VPS 76.13.245.174)", fill="#334155", font=header_font)
    
    gateways = [
        ("Nginx Reverse Proxy & SSL", "HTTPS Termination / Port 80, 443", (80, 290, 780, 345)),
        ("UFW Firewall & SlowAPI", "Rate Limiting & IP Abuse Protection", (820, 290, 1520, 345)),
    ]
    for name, sub, box in gateways:
        draw_rounded_box(draw, box, radius=8, fill="#FFFFFF", outline="#94A3B8", width=2)
        draw.text((box[0] + 20, box[1] + 12), name, fill="#0F172A", font=box_title_font)
        draw.text((box[0] + 20, box[1] + 34), sub, fill="#64748B", font=sub_font)

    # 3. CORE APPLICATION CONTAINER (FastAPI)
    draw_rounded_box(draw, (40, 400, 1020, 910), radius=16, fill="#FFFFFF", outline="#3B82F6", width=3)
    draw.text((60, 415), "AM5 BACKEND CORE APPLICATION (FastAPI / Uvicorn :8000)", fill="#1E3A8A", font=header_font)
    
    app_boxes = [
        ("API Router (app/api/v1)", "25+ Modular Sub-Routers (Auth, Vendors, Accounting, etc.)", "#2563EB", (70, 460, 990, 525)),
        ("Validation & DTO (app/schemas)", "Pydantic v2 Request Validation & Response Serialization", "#0284C7", (70, 545, 990, 610)),
        ("Business Logic Services (app/services)", "OTP, Subscriptions, Payments, Ledgers, Analytics", "#4F46E5", (70, 630, 990, 715)),
        ("Data Access Repositories (app/repositories)", "Async Query Abstraction & CRUD Operations", "#7C3AED", (70, 735, 990, 805)),
        ("APScheduler Cron Workers", "Morning/Evening Reminders, Booking Timeouts, Vendor Logs", "#D97706", (70, 825, 990, 890)),
    ]
    for name, sub, col, box in app_boxes:
        draw_rounded_box(draw, box, radius=8, fill="#F8FAFC", outline=col, width=2)
        draw.text((box[0] + 20, box[1] + 12), name, fill="#0F172A", font=box_title_font)
        draw.text((box[0] + 20, box[1] + 38), sub, fill="#475569", font=sub_font)

    # 4. PERSISTENCE & CACHE (Right side)
    draw_rounded_box(draw, (1060, 400, 1560, 640), radius=16, fill="#F0FDF4", outline="#86EFAC", width=2)
    draw.text((1080, 415), "PERSISTENCE & CACHE", fill="#166534", font=header_font)
    
    db_boxes = [
        ("PostgreSQL 15 (PostGIS)", "Port 5432 • SQLAlchemy 2.0 (asyncpg)", "#16A34A", (1080, 460, 1540, 535)),
        ("Redis 7 (Alpine)", "Port 6379 • Session Cache & OTP Verification", "#DC2626", (1080, 555, 1540, 625)),
    ]
    for name, sub, col, box in db_boxes:
        draw_rounded_box(draw, box, radius=8, fill="#FFFFFF", outline=col, width=2)
        draw.text((box[0] + 20, box[1] + 14), name, fill="#0F172A", font=box_title_font)
        draw.text((box[0] + 20, box[1] + 42), sub, fill="#475569", font=sub_font)

    # 5. EXTERNAL INTEGRATIONS (Right Bottom)
    draw_rounded_box(draw, (1060, 660, 1560, 910), radius=16, fill="#FAF5FF", outline="#D8B4FE", width=2)
    draw.text((1080, 675), "EXTERNAL INTEGRATIONS", fill="#6B21A8", font=header_font)
    
    third_parties = [
        ("Firebase Admin SDK", "FCM Push Notifications & User Authentication", (1080, 715, 1540, 770)),
        ("Razorpay Payment Gateway", "Online Payments, Webhooks, Settlements", (1080, 780, 1540, 835)),
        ("AWS S3 & SMS Gateways", "Cloud Media Storage & Fast2SMS OTP Engine", (1080, 845, 1540, 900)),
    ]
    for name, sub, box in third_parties:
        draw_rounded_box(draw, box, radius=6, fill="#FFFFFF", outline="#C084FC", width=1)
        draw.text((box[0] + 16, box[1] + 10), name, fill="#0F172A", font=box_title_font)
        draw.text((box[0] + 16, box[1] + 32), sub, fill="#64748B", font=sub_font)

    # Connecting Arrows
    draw_arrow(draw, (280, 175), (280, 290), color="#3B82F6", width=4)
    draw_arrow(draw, (740, 175), (740, 290), color="#10B981", width=4)
    draw_arrow(draw, (1260, 175), (1260, 290), color="#8B5CF6", width=4)
    
    draw_arrow(draw, (530, 345), (530, 460), color="#2563EB", width=4)
    draw_arrow(draw, (990, 770), (1080, 500), color="#16A34A", width=4) # Repo to DB
    draw_arrow(draw, (990, 675), (1080, 590), color="#DC2626", width=4) # Service to Redis
    draw_arrow(draw, (990, 700), (1080, 790), color="#9333EA", width=4) # Service to 3rd party

    path = os.path.join(DIAGRAM_DIR, "system_arch.png")
    img.save(path, "PNG")
    return path

def generate_request_flow_diagram():
    W, H = 1600, 360
    img = Image.new("RGBA", (W, H), "#FFFFFF")
    draw = ImageDraw.Draw(img)

    step_font = get_font(13, bold=True)
    box_font = get_font(16, bold=True)
    sub_font = get_font(12, bold=False)

    steps = [
        ("1. HTTP Request", "Client Request", "Headers / JSON Payload", "#3B82F6", 40),
        ("2. API Endpoint", "FastAPI Router", "Path & Param Binding", "#2563EB", 350),
        ("3. Validation", "Pydantic Schema", "DTO Serialization", "#0284C7", 660),
        ("4. Business Logic", "Service Layer", "Rules & Calculations", "#4F46E5", 970),
        ("5. Data Access", "Repository / DB", "Async SQL & Postgres", "#16A34A", 1280),
    ]

    for title, name, sub, col, x in steps:
        box = (x, 70, x + 270, 270)
        draw_rounded_box(draw, box, radius=12, fill="#F8FAFC", outline=col, width=2)
        # Badge
        draw_rounded_box(draw, (x + 15, 85, x + 255, 120), radius=6, fill=col, outline=col)
        draw.text((x + 25, 92), title, fill="#FFFFFF", font=step_font)
        draw.text((x + 20, 145), name, fill="#0F172A", font=box_font)
        draw.text((x + 20, 185), sub, fill="#64748B", font=sub_font)
        
        # Draw forward arrow if not last
        if x < 1280:
            draw_arrow(draw, (x + 270, 170), (x + 345, 170), color="#64748B", width=3, arrow_size=8)

    path = os.path.join(DIAGRAM_DIR, "request_flow.png")
    img.save(path, "PNG")
    return path

# -------------------------------------------------------------
# 2. Numbered Canvas for Professional Footer & Header
# -------------------------------------------------------------
class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 9)
        self.setFillColor(colors.HexColor("#64748B"))
        
        # Header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(54, 792 - 36, "AM5 Marketplace Backend — System Architecture & Technical Design")
            self.setStrokeColor(colors.HexColor("#E2E8F0"))
            self.setLineWidth(0.75)
            self.line(54, 792 - 42, 612 - 54, 792 - 42)

        # Footer
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(612 - 54, 36, page_str)
        self.drawString(54, 36, "CONFIDENTIAL — FOR INTERNAL & STAKEHOLDER USE ONLY")
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.75)
        self.line(54, 48, 612 - 54, 48)
        
        self.restoreState()

# -------------------------------------------------------------
# 3. PDF Builder
# -------------------------------------------------------------
def build_pdf():
    print("Generating diagrams...")
    sys_arch_img = generate_system_arch_diagram()
    req_flow_img = generate_request_flow_diagram()

    print("Assembling PDF document...")
    doc = SimpleDocTemplate(
        PDF_PATH,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54
    )

    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=6
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#2563EB"),
        spaceAfter=15
    )

    h1_style = ParagraphStyle(
        'Heading1_Custom',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=19,
        textColor=colors.HexColor("#1E3A8A"),
        spaceBefore=14,
        spaceAfter=8,
        keepWithNext=True
    )

    h2_style = ParagraphStyle(
        'Heading2_Custom',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#0F172A"),
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'Body_Custom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#334155"),
        spaceAfter=6
    )

    bullet_style = ParagraphStyle(
        'Bullet_Custom',
        parent=body_style,
        leftIndent=15,
        firstLineIndent=-10,
        spaceAfter=4
    )

    table_cell = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#1E293B")
    )

    table_header = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#FFFFFF")
    )

    elements = []

    # Title Banner Block
    elements.append(Paragraph("AM5 Marketplace Backend", title_style))
    elements.append(Paragraph("System Architecture & Technical Design Document", subtitle_style))
    
    meta_table_data = [
        [
            Paragraph("<b>Version:</b> 2.4 (Production)", table_cell),
            Paragraph("<b>Runtime:</b> Python 3.11 / FastAPI", table_cell),
            Paragraph("<b>Host:</b> Hostinger VPS (76.13.245.174)", table_cell)
        ],
        [
            Paragraph("<b>Database:</b> PostgreSQL 15 (PostGIS)", table_cell),
            Paragraph("<b>Cache:</b> Redis 7 (Alpine)", table_cell),
            Paragraph("<b>Date:</b> September 2026", table_cell)
        ]
    ]
    meta_table = Table(meta_table_data, colWidths=[160, 170, 174])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E1")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 12))

    # 1. Executive Summary
    elements.append(Paragraph("1. Executive Summary", h1_style))
    elements.append(Paragraph(
        "The <b>AM5 Marketplace Backend</b> is a robust, asynchronous RESTful API engineered to power the high-volume AM5 multi-sided marketplace. "
        "It serves Flutter mobile applications (Customer and Vendor apps) and React/TypeScript management web panels (SuperAdmin, Telecaller, Accounting & HR). "
        "Built on a <b>Clean Layered Architecture (Service-Repository Pattern)</b>, it ensures strict separation of concerns, high testability, and async throughput.",
        body_style
    ))

    # 2. High-Level Architecture Diagram
    elements.append(Paragraph("2. High-Level System Architecture", h1_style))
    elements.append(Paragraph(
        "The system employs a containerized micro-service ready architecture where incoming traffic is securely routed through an Edge/Reverse Proxy layer to the core asynchronous FastAPI application.",
        body_style
    ))
    
    # Insert System Architecture Diagram (Fit to page width 504 pt)
    elements.append(RLImage(sys_arch_img, width=504, height=299))
    elements.append(Spacer(1, 8))

    elements.append(PageBreak())

    # 3. Layered Code Architecture & Request Flow
    elements.append(Paragraph("3. Layered Code Architecture & Request Lifecycle", h1_style))
    elements.append(Paragraph(
        "The codebase is strictly structured into 5 decoupled layers. Every client interaction follows a predictable, type-safe lifecycle from HTTP request to database persistence:",
        body_style
    ))

    # Insert Request Flow Diagram
    elements.append(RLImage(req_flow_img, width=504, height=113))
    elements.append(Spacer(1, 10))

    # Layers Detailed Table
    layer_table_data = [
        [Paragraph("Layer", table_header), Paragraph("Directory", table_header), Paragraph("Key Responsibilities & Tech", table_header)],
        [
            Paragraph("<b>1. Presentation</b>", table_cell),
            Paragraph("<code>app/api/v1/</code>", table_cell),
            Paragraph("FastAPI <code>APIRouter</code> controllers, path routing, HTTP headers, status codes, query parsing.", table_cell)
        ],
        [
            Paragraph("<b>2. Schema / DTO</b>", table_cell),
            Paragraph("<code>app/schemas/</code>", table_cell),
            Paragraph("Pydantic v2 strict models for incoming payload validation and outbound JSON serialization.", table_cell)
        ],
        [
            Paragraph("<b>3. Service (Logic)</b>", table_cell),
            Paragraph("<code>app/services/</code>", table_cell),
            Paragraph("Core business rules, state machines, OTP workflows, ledger calculations, and external APIs.", table_cell)
        ],
        [
            Paragraph("<b>4. Repository</b>", table_cell),
            Paragraph("<code>app/repositories/</code>", table_cell),
            Paragraph("Data access abstraction layer encapsulating complex async SQLAlchemy queries and transactions.", table_cell)
        ],
        [
            Paragraph("<b>5. Persistence</b>", table_cell),
            Paragraph("<code>app/models/</code>", table_cell),
            Paragraph("SQLAlchemy 2.0 ORM entities with PostgreSQL 15 & PostGIS schema definitions and relationships.", table_cell)
        ],
    ]
    layer_table = Table(layer_table_data, colWidths=[100, 110, 294])
    layer_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E1")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor("#FFFFFF"), colors.HexColor("#F8FAFC")]),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(layer_table)
    elements.append(Spacer(1, 12))

    # 4. Functional Subsystems
    elements.append(Paragraph("4. Core Functional Modules", h1_style))
    
    modules_data = [
        [Paragraph("Domain Subsystem", table_header), Paragraph("Capabilities & Business Value", table_header)],
        [
            Paragraph("<b>Auth & RBAC</b>", table_cell),
            Paragraph("Multi-role JWT auth for Vendors, Customers, Admins, HR, and Telecallers with FastAPI <code>Depends</code> guards.", table_cell)
        ],
        [
            Paragraph("<b>Vendor Lifecycle</b>", table_cell),
            Paragraph("Step-by-step onboarding, service catalog mapping, visiting charges, city verification, and document review.", table_cell)
        ],
        [
            Paragraph("<b>Subscriptions & Orders</b>", table_cell),
            Paragraph("Tiered plan management (1499, Custom, One-Rupee), automated renewals, and Razorpay webhook reconciliation.", table_cell)
        ],
        [
            Paragraph("<b>Accounting & Payroll</b>", table_cell),
            Paragraph("Double-entry bookkeeping, chart of accounts, company expense ledgers, monthly vendor reports, and payroll tracking.", table_cell)
        ],
        [
            Paragraph("<b>Marketing & Telecalling</b>", table_cell),
            Paragraph("Lead assignment engine, telecaller call logs, incentive calculation, and conversion analytics.", table_cell)
        ],
        [
            Paragraph("<b>Developer Portal & HR</b>", table_cell),
            Paragraph("Internal sprint management, project heads, bug tracking, and employee career management.", table_cell)
        ],
    ]
    modules_table = Table(modules_data, colWidths=[140, 364])
    modules_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E1")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor("#FFFFFF"), colors.HexColor("#F8FAFC")]),
        ('TOPPADDING', (0, 0), (-1, -1), 4.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(modules_table)
    elements.append(Spacer(1, 10))

    elements.append(PageBreak())

    # 5. Security, Observability & Infrastructure
    elements.append(Paragraph("5. Security, Observability & Cron Automation", h1_style))
    
    elements.append(Paragraph("<b>Security & Traffic Control:</b>", h2_style))
    elements.append(Paragraph("• <b>Rate Limiting (SlowAPI):</b> Protects critical endpoints (OTP generation, authentication, payment verification) against brute-force and DDoS attacks.", bullet_style))
    elements.append(Paragraph("• <b>CORS & Middleware:</b> Restricts cross-origin browser requests strictly to authorized domains (<code>am5royal.com</code>, <code>admin.am5royal.com</code>, etc.).", bullet_style))
    elements.append(Paragraph("• <b>Asynchronous Connection Pooling:</b> Database connections are multiplexed via <code>asyncpg</code> and managed safely with asynchronous context managers.", bullet_style))

    elements.append(Spacer(1, 4))
    elements.append(Paragraph("<b>Observability & Logging:</b>", h2_style))
    elements.append(Paragraph("• <b>Structured JSON Logging (<code>structlog</code>):</b> Produces machine-parseable logs with trace IDs, query context, and error payloads for rapid troubleshooting.", bullet_style))
    elements.append(Paragraph("• <b>Error Tracking (Sentry):</b> Real-time exception capture and alert notifications for unhandled server errors.", bullet_style))

    elements.append(Spacer(1, 4))
    elements.append(Paragraph("<b>Background Cron Automation (APScheduler):</b>", h2_style))
    elements.append(Paragraph("• <b>Customer Reminders:</b> Automated morning, afternoon, and evening service reminder push notifications.", bullet_style))
    elements.append(Paragraph("• <b>Booking Acceptance Timeouts:</b> Automatically reassigns or cancels unacknowledged service requests.", bullet_style))
    elements.append(Paragraph("• <b>Monthly Vendor Histories:</b> Automatically snapshots vendor performance metrics, ratings, and revenue at month-end.", bullet_style))

    elements.append(Spacer(1, 12))

    # 6. Deployment & Infrastructure
    elements.append(Paragraph("6. Deployment & VPS Infrastructure", h1_style))
    
    infra_data = [
        [Paragraph("Component", table_header), Paragraph("Configuration Details", table_header)],
        [
            Paragraph("<b>Target Host</b>", table_cell),
            Paragraph("Hostinger VPS (Dedicated IP: <code>76.13.245.174</code>), Ubuntu Linux.", table_cell)
        ],
        [
            Paragraph("<b>Containerization</b>", table_cell),
            Paragraph("Docker Compose running <code>am5_backend</code> (FastAPI) and <code>am5_redis</code> (Redis 7).", table_cell)
        ],
        [
            Paragraph("<b>Database</b>", table_cell),
            Paragraph("PostgreSQL 15 with PostGIS spatial extensions on port 5432.", table_cell)
        ],
        [
            Paragraph("<b>CI/CD Deployment</b>", table_cell),
            Paragraph("Automated Paramiko SSH/SFTP deployment pipeline with atomic container builds and auto-running migrations.", table_cell)
        ],
        [
            Paragraph("<b>Health Endpoint</b>", table_cell),
            Paragraph("<code>GET /health</code> returning <code>{\"status\":\"ok\"}</code> for uptime and container health probes.", table_cell)
        ],
    ]
    infra_table = Table(infra_data, colWidths=[140, 364])
    infra_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E1")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor("#FFFFFF"), colors.HexColor("#F8FAFC")]),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(infra_table)

    # Build document
    doc.build(elements, canvasmaker=NumberedCanvas)
    print(f"PDF successfully generated at: {PDF_PATH}")

if __name__ == "__main__":
    build_pdf()
