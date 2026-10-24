from django.db import models


class Residency(models.TextChoices):
    RESIDENT = 'resident', 'Resident'
    NON_RESIDENT = 'non_resident', 'Non-resident'


class AgeCategory(models.TextChoices):
    ADULT = 'adult', 'Adult'
    CHILD = 'child', 'Child'


class AccommodationLevel(models.TextChoices):
    BUDGET = 'budget', 'Budget'
    MID_RANGE = 'mid_range', 'Mid-range'
    LUXURY = 'luxury', 'Luxury'


class GoalStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    ACTIVE = 'active', 'Active'
    PAUSED = 'paused', 'Paused'
    COMPLETED = 'completed', 'Completed'
    CANCELLED = 'cancelled', 'Cancelled'
    EXPIRED = 'expired', 'Expired'


class PaymentFrequency(models.TextChoices):
    WEEKLY = 'weekly', 'Weekly'
    BI_WEEKLY = 'bi_weekly', 'Every 2 weeks'
    MONTHLY = 'monthly', 'Monthly'
    CUSTOM = 'custom', 'Custom'


class InstallmentStatus(models.TextChoices):
    UPCOMING = 'upcoming', 'Upcoming'
    PAID = 'paid', 'Paid'
    PARTIALLY_PAID = 'partially_paid', 'Partially paid'
    MISSED = 'missed', 'Missed'


class PaymentMethod(models.TextChoices):
    MPESA = 'mpesa', 'M-Pesa'
    AIRTEL_MONEY = 'airtel_money', 'Airtel Money'
    MIXX_BY_YAS = 'mixx_by_yas', 'Mixx by Yas'
    HALO_PESA = 'halo_pesa', 'HaloPesa'
    CARD = 'card', 'Card'


MOBILE_MONEY_METHODS = {
    PaymentMethod.MPESA, PaymentMethod.AIRTEL_MONEY, PaymentMethod.MIXX_BY_YAS, PaymentMethod.HALO_PESA,
}


class PaymentStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    SUCCESS = 'success', 'Successful'
    FAILED = 'failed', 'Failed'
    REFUNDED = 'refunded', 'Refunded'


class BookingStatus(models.TextChoices):
    CONFIRMED = 'confirmed', 'Confirmed'
    CANCELLED = 'cancelled', 'Cancelled'
    COMPLETED = 'completed', 'Completed'


class KycStatus(models.TextChoices):
    NOT_REQUIRED = 'not_required', 'Not required'
    PENDING = 'pending', 'Pending review'
    VERIFIED = 'verified', 'Verified'
    REJECTED = 'rejected', 'Rejected'


class TripDocumentType(models.TextChoices):
    VOUCHER = 'voucher', 'Voucher'
    PACKING_LIST = 'packing_list', 'Packing list'
    OPERATOR_CONTACTS = 'operator_contacts', 'Operator contacts'
    OTHER = 'other', 'Document'


class NotificationType(models.TextChoices):
    PAYMENT_SUCCESS = 'payment_success', 'Payment success'
    PAYMENT_FAILED = 'payment_failed', 'Payment failed'
    INSTALLMENT_DUE = 'installment_due', 'Installment due'
    INSTALLMENT_MISSED = 'installment_missed', 'Installment missed'
    GOAL_COMPLETED = 'goal_completed', 'Goal completed'
    GOAL_PAUSED = 'goal_paused', 'Goal paused'
    GOAL_EXPIRED = 'goal_expired', 'Goal expired'
    GOAL_CANCELLED = 'goal_cancelled', 'Goal cancelled'
    KYC_VERIFIED = 'kyc_verified', 'Identity verified'
    KYC_REJECTED = 'kyc_rejected', 'Identity rejected'
    BOOKING_UPDATED = 'booking_updated', 'Booking updated'
    ANNOUNCEMENT = 'announcement', 'Announcement'
