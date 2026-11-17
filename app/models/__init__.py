from .catalog import (
    ServiceCategory, ServiceSubcategory, Package, SubPackage,
    PackageBenefit, PackageInclusionStep, PackageInclusionBullet,
    PackageExclusionStep, PackageExclusionBullet, PackagePrecaution,
    PackageBrand, PackageSafety, PackageSection
)
from .user_location import City, Zone, Customer, CustomerPreference, Address, User
from .orders import Order, OrderItem, Payment
from .shop import Product, CartItem, ShopOrder, ShopOrderItem
from .search_log import SearchQueryStat
from .notification import Notification
from .booking_call import BookingCall
from .booking_offer import BookingOffer, VendorLeadHistory
from .chat import ChatThread, ChatMessage
from .support import SupportTicketMessage
from .customer_billing import (
    CustomerWallet, CustomerWalletTransaction, BookingFeedback, Coupon,
    CouponRedemption, BookingPayment, Invoice,
)
from .engagement import FAQ, Review, Ticket, Banner, Testimonial
from .employee import Employee, WithdrawalRequest
from .vendor import Vendor, VendorSubCategory, VendorDocument, VendorAvailability, VendorService, VendorServiceMedia, VendorAuditLog
from .marketing import MarketingLead, MarketingCollateral
from .freelancer import Freelancer
from .points_history import PointsHistory
from .vendor_media import VendorMedia
from .vendor_extras import VendorSalesMedia, VendorOffer, VendorNewLaunch, VendorMonthlyHistory
from .verification_incentive import VerificationIncentive
from .career import JobOpening, JobApplication
from .call_log import TelecallerCallLog
from .developer_portal import (
    DevProject,
    DevProjectMember,
    DevProjectModule,
    DevProjectApi,
    DevTask,
    DevTaskComment,
    DevBug,
    DevBugComment,
    DevBugActivityHistory,
    DevNotification,
    DevDeployment,
    DevAuditLog,
)
from .accounting import (
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
from freelance_api.models import (
    FreelancerKycDocument,
    FreelancerKycSubmission,
    FreelancerFaceVerificationSession,
    FreelancerReferralLink,
    FreelancerReferralReward,
    FreelancerInstallationRule,
    FreelancerInstallationTracking,
    FreelancerRewardItem,
    FreelancerWalletTransaction,
    FreelancerPayoutRequest,
    FreelancerSetting,
    FreelancerNotification,
    FreelancerDeviceToken,
    FreelancerSupportTicket,
    FreelancerLegalPage,
    FreelancerLegalAcceptance,
    FreelancerBanner,
    FreelancerDemoVideo,
    FreelancerFaq,
)

# Category modules (models must be imported so create_all sees them)
import app.categories.real_estate.models  # noqa: E402,F401
