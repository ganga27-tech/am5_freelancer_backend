from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from freelance_api.models import (
    FreelancerInstallationRule,
    FreelancerBanner,
    FreelancerDemoVideo,
    FreelancerFaq,
    FreelancerLegalPage,
)

async def seed_freelance_defaults(db: AsyncSession):
    """Seed initial defaults for banners, demo videos, reward rules, FAQs and legal pages."""
    now = datetime.utcnow()

    # 1. Installation Rules
    rule_check = await db.execute(select(FreelancerInstallationRule).limit(1))
    if not rule_check.scalar_one_or_none():
        rules = [
            FreelancerInstallationRule(
                app_type="customer",
                milestone_target=300,
                reward_amount=1500.0,
                currency="INR",
                voucher_type="amazon",
                voucher_title="₹1,500 Amazon Gift Voucher",
                voucher_value=1500.0,
                conditions="300 genuine customer app installations with 30-day retention",
                retention_days=30,
                is_active=True
            ),
            FreelancerInstallationRule(
                app_type="customer",
                milestone_target=500,
                reward_amount=3000.0,
                currency="INR",
                voucher_type="amazon",
                voucher_title="₹3,000 Amazon Gift Voucher",
                voucher_value=3000.0,
                conditions="500 genuine customer app installations with 30-day retention",
                retention_days=30,
                is_active=True
            ),
            FreelancerInstallationRule(
                app_type="customer",
                milestone_target=1000,
                reward_amount=7500.0,
                currency="INR",
                voucher_type="cash",
                voucher_title="₹7,500 Direct Cash Payout",
                voucher_value=7500.0,
                conditions="1,000 genuine customer app installations with 30-day retention",
                retention_days=30,
                is_active=True
            ),
            FreelancerInstallationRule(
                app_type="customer",
                milestone_target=2500,
                reward_amount=20000.0,
                currency="INR",
                voucher_type="cash",
                voucher_title="₹20,000 Super Partner Cash Reward",
                voucher_value=20000.0,
                conditions="2,500 genuine customer app installations with 30-day retention",
                retention_days=30,
                is_active=True
            ),
            FreelancerInstallationRule(
                app_type="vendor",
                milestone_target=50,
                reward_amount=2500.0,
                currency="INR",
                voucher_type="cash",
                voucher_title="₹2,500 Vendor Onboarding Milestone",
                voucher_value=2500.0,
                conditions="50 verified active vendors onboarded via referral link",
                retention_days=30,
                is_active=True
            ),
            FreelancerInstallationRule(
                app_type="vendor",
                milestone_target=150,
                reward_amount=8000.0,
                currency="INR",
                voucher_type="cash",
                voucher_title="₹8,000 Vendor Leadership Bonus",
                voucher_value=8000.0,
                conditions="150 verified active vendors onboarded via referral link",
                retention_days=30,
                is_active=True
            ),
        ]
        db.add_all(rules)

    # 2. Banners
    banner_check = await db.execute(select(FreelancerBanner).limit(1))
    if not banner_check.scalar_one_or_none():
        banners = [
            FreelancerBanner(
                banner_id="bnr_home_01",
                title="Earn Up to ₹50,000 Monthly",
                subtitle="Join the AM5 Partner Network and earn recurring income with every referral.",
                image_url="https://am5royal.com/assets/banners/freelancer_hero.jpg",
                mobile_image_url="https://am5royal.com/assets/banners/freelancer_hero_mobile.jpg",
                placement="home",
                target_audience="freelancer",
                action_type="navigate",
                action_value="/referrals",
                priority=100,
                is_active=True
            ),
            FreelancerBanner(
                banner_id="bnr_services_01",
                title="Promote Premium AC & Home Cleaning",
                subtitle="High conversion rates and 10% instant commission on home services.",
                image_url="https://am5royal.com/assets/banners/services_banner.jpg",
                placement="services",
                target_audience="freelancer",
                action_type="navigate",
                action_value="/services",
                priority=90,
                is_active=True
            ),
            FreelancerBanner(
                banner_id="bnr_refer_01",
                title="Share Links, Win Amazon Vouchers",
                subtitle="Every 300 verified customer app downloads unlocks ₹1,500 vouchers.",
                image_url="https://am5royal.com/assets/banners/refer_earn.jpg",
                placement="refer_earn",
                target_audience="freelancer",
                action_type="navigate",
                action_value="/installation-rewards",
                priority=80,
                is_active=True
            ),
            FreelancerBanner(
                banner_id="bnr_install_01",
                title="App Download Challenge 2026",
                subtitle="Track live installations and unlock milestone bonuses.",
                image_url="https://am5royal.com/assets/banners/install_rewards.jpg",
                placement="installation_activation",
                target_audience="freelancer",
                action_type="navigate",
                action_value="/installation-rewards",
                priority=70,
                is_active=True
            ),
            FreelancerBanner(
                banner_id="bnr_wallet_01",
                title="Instant Payouts to Any Indian Bank",
                subtitle="Complete your KYC & bank details to enable 24-hr fast withdrawals.",
                image_url="https://am5royal.com/assets/banners/wallet_payouts.jpg",
                placement="earnings_wallet",
                target_audience="freelancer",
                action_type="navigate",
                action_value="/wallet",
                priority=60,
                is_active=True
            ),
            FreelancerBanner(
                banner_id="bnr_profile_01",
                title="Verify Your KYC Today",
                subtitle="Verify Aadhaar & PAN to unlock Platinum commission slabs.",
                image_url="https://am5royal.com/assets/banners/kyc_verify.jpg",
                placement="profile",
                target_audience="freelancer",
                action_type="navigate",
                action_value="/profile/kyc",
                priority=50,
                is_active=True
            ),
        ]
        db.add_all(banners)

    # 3. Demo Videos
    video_check = await db.execute(select(FreelancerDemoVideo).limit(1))
    if not video_check.scalar_one_or_none():
        videos = [
            FreelancerDemoVideo(
                video_id="vid_cust_app",
                title="Customer App Walkthrough & Booking Process",
                video_type="customer_app",
                audience="freelancer",
                video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                thumbnail_url="https://am5royal.com/assets/videos/customer_app_thumb.jpg",
                duration="04:15",
                display_order=1,
                is_active=True
            ),
            FreelancerDemoVideo(
                video_id="vid_vendor_app",
                title="Vendor Onboarding & Job Acceptance Guide",
                video_type="vendor_app",
                audience="freelancer",
                video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                thumbnail_url="https://am5royal.com/assets/videos/vendor_app_thumb.jpg",
                duration="05:30",
                display_order=2,
                is_active=True
            ),
            FreelancerDemoVideo(
                video_id="vid_rewards_guide",
                title="How Referral Points & Milestones Work",
                video_type="rewards_guide",
                audience="freelancer",
                video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                thumbnail_url="https://am5royal.com/assets/videos/rewards_guide_thumb.jpg",
                duration="03:45",
                display_order=3,
                is_active=True
            ),
            FreelancerDemoVideo(
                video_id="vid_freelancer_guide",
                title="Maximizing Your Daily Earnings on AM5",
                video_type="freelancer_guide",
                audience="freelancer",
                video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                thumbnail_url="https://am5royal.com/assets/videos/freelancer_guide_thumb.jpg",
                duration="06:20",
                display_order=4,
                is_active=True
            ),
        ]
        db.add_all(videos)

    # 4. FAQs
    faq_check = await db.execute(select(FreelancerFaq).limit(1))
    if not faq_check.scalar_one_or_none():
        faqs = [
            FreelancerFaq(
                faq_id="faq_01",
                question="How do I earn referral points?",
                answer="Share your unique referral links with customers or vendors. When a referred customer books a service or a vendor registers and is verified, points are automatically credited to your wallet.",
                category="referrals",
                audience="freelancer",
                display_order=1,
                is_active=True
            ),
            FreelancerFaq(
                faq_id="faq_02",
                question="How long are referral links valid?",
                answer="You can generate referral links with either 7 or 15 days validity. Expired links cannot be used for attribution, but you can generate unlimited new links anytime.",
                category="referrals",
                audience="freelancer",
                display_order=2,
                is_active=True
            ),
            FreelancerFaq(
                faq_id="faq_03",
                question="What is the minimum withdrawal amount?",
                answer="The minimum payout withdrawal threshold is ₹500. Withdrawals are processed directly into your registered bank account within 24 to 48 business hours.",
                category="wallet",
                audience="freelancer",
                display_order=3,
                is_active=True
            ),
            FreelancerFaq(
                faq_id="faq_04",
                question="Is KYC mandatory for receiving payouts?",
                answer="Yes, basic KYC (Aadhaar or PAN) and verified bank account details are mandatory under Indian financial regulations to disburse payout rewards.",
                category="kyc",
                audience="freelancer",
                display_order=4,
                is_active=True
            ),
        ]
        db.add_all(faqs)

    # 5. Legal Pages
    legal_check = await db.execute(select(FreelancerLegalPage).limit(1))
    if not legal_check.scalar_one_or_none():
        legal_pages = [
            FreelancerLegalPage(
                slug="privacy-policy",
                title="AM5 Royal Freelancer Privacy Policy",
                content="Privacy Policy details regarding data protection, banking security, and KYC adherence.",
                version="1.0",
                effective_date=now - timedelta(days=30),
                last_updated_date=now,
                is_active=True
            ),
            FreelancerLegalPage(
                slug="terms-and-conditions",
                title="AM5 Royal Freelancer Terms & Conditions",
                content="Terms of service, referral rules, anti-fraud compliance, and payout schedules.",
                version="1.0",
                effective_date=now - timedelta(days=30),
                last_updated_date=now,
                is_active=True
            )
        ]
        db.add_all(legal_pages)

    await db.commit()

