# campaign/views.py

from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from .serializers import (
    ParticipationSerializer,
    InfluencerCampaignSerializer,
    PolymorphicCampaignSerializer,
    TicketCampaignSerializer,
    MediaSellingCampaignSerializer,
    MeetAndGreetCampaignSerializer,
    CampaignWinnerSerializer,
    UpdateTicketCampaignSerializer,
    UpdateMeetAndGreetCampaignSerializer,
    UpdateMediaSellingCampaignSerializer,
    PolymorphicCampaignDetailSerializer,
    ProfileCampaignSerializer,
    UserCampaignSerializer,
    MediaAccessSerializer,
    AutoParticipateConfirmSerializer,
    MediaFileSerializer
)
import random
from .models import (
    Campaign,
    Participation,
    TicketCampaign,
    MeetAndGreetCampaign,
    MediaSellingCampaign,
    CampaignWinner,
    MediaFile,
    CreditSpend,
    EscrowRecord,
    MediaAccess,
)
from django.core.mail import send_mail
from django.contrib.auth import get_user_model
from django.db.models import Sum, Count, Q, Max
from decimal import Decimal
from django.conf import settings
import logging
from blockchain.utils import w3, contract
from web3.exceptions import ContractLogicError, TimeExhausted
import time
from campaign.utils import (
    select_random_winners,
    get_or_create_winner_conversation,
    assign_media_to_user,
    generate_presigned_s3_url,
    watermark_image,
)
from blockchain.tasks import register_campaign_on_chain, hold_for_campaign_on_chain
from django.db import transaction
from blockchain.tasks import (
    release_all_holds_for_campaign_task,
    refund_all_holds_for_campaign_task,
    save_onchain_action_info,
    save_transaction_info,
)
from celery import chain
from blockchain.models import OnChainAction, Transaction
from rest_framework.generics import ListAPIView
from django.shortcuts import get_object_or_404
from campaign.cloudfront_signer import generate_cloudfront_signed_url
from django.http import StreamingHttpResponse
import boto3
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.decorators import parser_classes
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.http import HttpResponseRedirect
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from datetime import timedelta, timezone
import datetime as dt
from django.http import HttpResponseRedirect
from botocore.signers import CloudFrontSigner
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from django.utils import timezone as dj_timezone
from web3.exceptions import TransactionNotFound
from django.db.models.functions import TruncDate, Coalesce  # built-in: SQL DATE() & COALESCE(NULL, fallback)
from django.db.models import Sum, Count, Q, Value, IntegerField  # built-in: aggregations & query helpers
from decimal import Decimal
from datetime import timedelta

User = get_user_model()

logger = logging.getLogger(__name__)

SALT = getattr(settings, "MEDIA_TOKEN_SALT", "media-access")
TTL = getattr(settings, "MEDIA_TOKEN_TTL", 300)
TX_MAX_WAIT = getattr(settings, "TX_RECEIPT_MAX_WAIT_SECONDS", 60)
TX_POLL_LATENCY = getattr(settings, "TX_RECEIPT_POLL_LATENCY", 2)

def wait_for_tx_receipt(
    tx_hash: str, poll_interval: float = 2.0, timeout: float = 120.0
):
    """
    Polls get_transaction_receipt(tx_hash) until the receipt is non-null or we hit timeout.
    Returns the receipt dict once mined, or raises TimeoutError.
    """
    start = time.time()
    while True:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        if receipt is not None:
            # tx is mined; receipt.status == 1 means success, 0 means reverted
            return receipt

        if time.time() - start > timeout:
            raise TimeoutError(f"Timed out waiting for tx {tx_hash}")

        time.sleep(poll_interval)

class FanAnalyticsView(APIView):
    """
    Returns analytics data for the authenticated fan:
      - Total distinct campaigns participated in.
      - Total participation records.
      - Total spendings (sum of amounts from participations).
      - Total tickets purchased (for ticket and meet & greet campaigns).
      - Total number of distinct campaign winnings.
      - Placeholder for additional performance data.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Ensure the authenticated user is a fan
        if request.user.user_type != "fan":
            return Response(
                {"error": "Only fans can access this analytics endpoint."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Total distinct campaigns participated in
        total_campaigns_participated = (
            Participation.objects.filter(fan=request.user)
            .values("campaign")
            .distinct()
            .count()
        )

        # Total participation count (all participation records)
        total_participation_count = Participation.objects.filter(
            fan=request.user
        ).count()

        # Total spendings
        spending_agg = Participation.objects.filter(fan=request.user).aggregate(
            total_spending=Sum("amount")
        )
        total_spending = spending_agg["total_spending"] or 0

        # Total tickets purchased (only for ticket and meet & greet campaigns)
        tickets_agg = Participation.objects.filter(
            fan=request.user, campaign__campaign_type__in=["ticket", "meet_greet"]
        ).aggregate(total_tickets=Sum("tickets_purchased"))
        total_tickets = tickets_agg["total_tickets"] or 0

        # Total winnings (count of distinct campaigns won by this fan)
        total_winnings = CampaignWinner.objects.filter(fan=request.user).count()

        # Placeholder for additional performance data
        performance_data = {}

        data = {
            "total_campaigns_participated": total_campaigns_participated,
            "total_participation_count": total_participation_count,
            "total_spending": total_spending,
            "total_tickets": total_tickets,
            "total_winnings": total_winnings,
            "performance_data": performance_data,
        }

        return Response(data, status=status.HTTP_200_OK)

class UnifiedEngagementView(APIView):
    """
    GET /campaign/dashboard/engagement/?days=30[&campaign_id=123]
    OR
    GET /campaign/dashboard/engagement/<campaign_id>/?days=30

    - If campaign_id is present → returns that campaign's engagement (owner-guarded)
    - Else → aggregates across *all* campaigns owned by the authenticated influencer
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, campaign_id=None):
        # ── AuthZ: Only influencers can access ────────────────────────────────
        user = request.user
        if getattr(user, "user_type", None) != "influencer":
            return Response({"error": "Only influencers can access engagement."}, status=status.HTTP_403_FORBIDDEN)

        # built-in: .get() reads query param safely; int() converts text → number
        q_campaign_id = request.query_params.get("campaign_id")
        if campaign_id is None and q_campaign_id:
            try:
                campaign_id = int(q_campaign_id)
            except ValueError:
                return Response({"error": "Invalid campaign_id."}, status=400)

        # built-in clamp for days: ensure reasonable range
        try:
            days = int(request.query_params.get("days", 30))
        except ValueError:
            days = 30
        days = max(1, min(days, 365))

        now_ts = dj_timezone.now()
        start_ts = now_ts - timedelta(days=days - 1)

        # Scope selection
        scope = "influencer"
        base_campaigns = Campaign.objects.filter(user=user)
        if campaign_id is not None:
            # owner check for single campaign
            try:
                campaign = base_campaigns.get(id=campaign_id)
            except Campaign.DoesNotExist:
                return Response({"error": "Campaign not found or you are not the owner."}, status=404)
            qs_part = Participation.objects.filter(campaign=campaign)
            scope = "campaign"
        else:
            campaign = None
            qs_part = Participation.objects.filter(campaign__user=user)

        # ── Totals (paid entries vs free) ─────────────────────────────────────
        # built-in: Coalesce(Sum(...), 0) → if NULL then 0
        paid_tickets = qs_part.aggregate(v=Coalesce(Sum("tickets_purchased", filter=Q(is_free_entry=False)), 0))["v"] or 0
        paid_media   = qs_part.aggregate(v=Coalesce(Sum("media_purchased",  filter=Q(is_free_entry=False)), 0))["v"] or 0
        total_entries_paid = int(paid_tickets) + int(paid_media)

        free_tickets = qs_part.aggregate(v=Coalesce(Sum("tickets_purchased", filter=Q(is_free_entry=True)), 0))["v"] or 0
        free_media   = qs_part.aggregate(v=Coalesce(Sum("media_purchased",  filter=Q(is_free_entry=True)), 0))["v"] or 0
        free_entries_count = int(free_tickets) + int(free_media)

        # built-in: Sum('amount') → total revenue; free entries have amount=0 anyway
        total_earning = qs_part.aggregate(v=Coalesce(Sum("amount"), Decimal("0")))["v"] or Decimal("0")

        # built-in: COUNT(DISTINCT fan)
        total_participants = qs_part.values("fan").distinct().count()

        # Likes + winners + goals
        if scope == "campaign":
            total_likes = campaign.likes.count()  # built-in: M2M count
            winners_count = campaign.winners.count()

            # entries_left = goal - paid
            specific = campaign.specific_campaign()
            if campaign.campaign_type == "media_selling":
                goal_total = getattr(specific, "total_media", 0) or 0
            else:
                goal_total = getattr(specific, "total_tickets", 0) or 0
        else:
            # built-in: aggregate likes across all campaigns of user
            total_likes = base_campaigns.aggregate(v=Coalesce(Count("likes"), 0))["v"] or 0
            winners_count = CampaignWinner.objects.filter(campaign__user=user).count()
            # goals across all owned campaigns
            ticket_goal = TicketCampaign.objects.filter(user=user).aggregate(v=Coalesce(Sum("total_tickets"), 0))["v"] or 0
            media_goal  = MediaSellingCampaign.objects.filter(user=user).aggregate(v=Coalesce(Sum("total_media"), 0))["v"] or 0
            goal_total  = int(ticket_goal) + int(media_goal)

        entries_left = max(0, int(goal_total) - total_entries_paid)  # built-in: max(a,b)

        # On-hold (sum Escrow held)
        escrow_qs = EscrowRecord.objects.filter(status="held")
        escrow_qs = escrow_qs.filter(campaign=campaign) if scope == "campaign" else escrow_qs.filter(campaign__user=user)
        escrow_agg = escrow_qs.aggregate(
            credits_on_hold=Coalesce(Sum("credit_amount"), 0),
            tt_on_hold=Coalesce(Sum("tt_amount"), 0),
        )
        credits_on_hold = int(escrow_agg["credits_on_hold"] or 0)
        tt_on_hold = int(escrow_agg["tt_on_hold"] or 0)

        # ── Time series (daily) ───────────────────────────────────────────────
        per_day = (
            qs_part.filter(created_at__date__gte=start_ts.date())
            .annotate(day=TruncDate("created_at"))                 # built-in: DATE(created_at)
            .values("day")                                         # built-in: GROUP BY day
            .annotate(
                entries_tickets=Coalesce(Sum("tickets_purchased", filter=Q(is_free_entry=False)), 0),
                entries_media=Coalesce(Sum("media_purchased",  filter=Q(is_free_entry=False)), 0),
                revenue=Coalesce(Sum("amount",                  filter=Q(is_free_entry=False)), Decimal("0")),
                participants=Count("fan", filter=Q(is_free_entry=False), distinct=True),
            )
            .order_by("day")
        )

        # build fixed buckets [start..today] so charts don’t have gaps
        day_index = {row["day"]: row for row in per_day}
        buckets, entries_series, revenue_series, participants_series = [], [], [], []
        for i in range(days):
            d = (start_ts + timedelta(days=i)).date()
            buckets.append(d.isoformat())
            row = day_index.get(d)
            if row:
                entries_series.append(int(row["entries_tickets"] or 0) + int(row["entries_media"] or 0))
                revenue_series.append(float(row["revenue"] or 0))
                participants_series.append(int(row["participants"] or 0))
            else:
                entries_series.append(0)
                revenue_series.append(0.0)
                participants_series.append(0)

        # ── Breakdowns (optional for UI) ──────────────────────────────────────
        payment_methods = list(
            qs_part.values("payment_method")
            .annotate(
                count=Count("id"),                                  # built-in: COUNT(*)
                amount=Coalesce(Sum("amount"), Decimal("0")),
            )
            .order_by("-count")
        )
        for pm in payment_methods:
            pm["amount"] = float(pm["amount"] or 0)

        # Top participants by entries
        top_raw = (
            qs_part.filter(is_free_entry=False)
            .values("fan")
            .annotate(
                t=Coalesce(Sum("tickets_purchased"), 0),
                m=Coalesce(Sum("media_purchased"), 0),
                amount=Coalesce(Sum("amount"), Decimal("0")),
            )
            .order_by("-t", "-m")[:5]
        )
        top_participants = []
        for row in top_raw:
            try:
                u = User.objects.get(pk=row["fan"])
            except User.DoesNotExist:
                continue
            user_data = UserCampaignSerializer(u, context={"request": request}).data
            user_data["profile"] = ProfileCampaignSerializer(u.profile, context={"request": request}).data
            top_participants.append({
                "user": user_data,
                "entries": int(row["t"] or 0) + int(row["m"] or 0),
                "amount": float(row["amount"] or 0),
            })

        # ── Response (shape compatible with your front-end) ───────────────────
        data = {
            "scope": scope,                         # "campaign" | "influencer"
            "campaign_id": campaign.id if campaign else None,
            "title": campaign.title if campaign else "All Campaigns",
            "campaign_type": campaign.campaign_type if campaign else "mixed",
            "deadline": campaign.deadline if campaign else None,
            "is_closed": campaign.is_closed if campaign else False,

            # cards
            "total_participants": total_participants,
            "total_likes": total_likes,
            "total_tickets_sold": total_entries_paid,   # kept for UI label
            "total_entries_sold": total_entries_paid,   # unified alias
            "total_earning": float(total_earning),
            "credits_on_hold": credits_on_hold,
            "tt_on_hold": tt_on_hold,
            "entries_left": entries_left,
            "winners_count": winners_count,
            "total_participations": qs_part.count(),    # built-in: COUNT(*)
            "free_entries_count": free_entries_count,
            "paid_entries_count": total_entries_paid,

            # charts
            "series": {
                "buckets": buckets,
                "entries": entries_series,
                "revenue": revenue_series,
                "participants": participants_series,
            },

            # breakdowns
            "breakdown": {
                "payment_methods": payment_methods,
                "top_participants": top_participants,
            },
        }
        return Response(data, status=200)


class CreateCampaignView(APIView):
    # built-in: tells DRF to use these parsers for incoming data
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        if user.user_type != "influencer":
            return Response(
                {"error": "Only influencers can create campaigns."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # 1) Validate & save to DB
        serializer = PolymorphicCampaignSerializer(
            data=request.data, context={"request": request}
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                # built-in: opens a DB transaction so on any exception the DB rolls back
                campaign = serializer.save(user=user)
                logger.info(f"Campaign type = {campaign.campaign_type}")

                # Log raw FILES to debug why getlist() might be empty
                logger.info(f"request.FILES = {request.FILES!r}")
                logger.info(f"Uploaded field names: {list(request.FILES.keys())}")

                if campaign.campaign_type == "media_selling":
                    # built-in: getlist() returns all uploaded files under this field name
                    files = request.FILES.getlist("media_files")
                    logger.info(f"Media files list = {files}")

                    for f in files:

                        processed = f
                        if f.content_type and f.content_type.startswith("image/"):
                            # put your brand or campaign title here
                            wtext = "meetyourfan.io"
                            processed = watermark_image(f, text=wtext, opacity=0.25)
                        # built-in: .save() on a Model instance writes it to the DB
                        media_file = MediaFile(campaign=campaign, file=processed)
                        media_file.save()

                        # built-in: get_or_create() tries to fetch an object matching the kwargs;
                        # if none exists, it creates one and returns (obj, True), else (obj, False)
                        media_access, created = MediaAccess.objects.get_or_create(
                            user=user, media_file=media_file
                        )
                        logger.info(
                            f"MediaAccess created={created} id={media_access.id}"
                        )

                    # nested serializer to include your newly saved media_files
                    response_serializer = MediaSellingCampaignSerializer(
                        campaign, context={"request": request}
                    )

                elif isinstance(campaign, TicketCampaign):
                    response_serializer = TicketCampaignSerializer(
                        campaign, context={"request": request}
                    )
                elif isinstance(campaign, MeetAndGreetCampaign):
                    response_serializer = MeetAndGreetCampaignSerializer(
                        campaign, context={"request": request}
                    )
                else:
                    return Response(
                        {"error": "Unknown campaign type."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # ──────────────────────────────────────────────────────────────────────────────
                # 2) Register on-chain
                # ──────────────────────────────────────────────────────────────────────────────
                try:
                    seller_id_int = int(request.user.user_id)
                except (TypeError, ValueError):
                    return Response(
                        {
                            "error": f"Invalid on-chain seller ID: {request.user.user_id!r}"
                        },
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

                # built-in: chain() chains multiple Celery tasks, passing the result of each to the next
                # .s() makes an immutable signature; apply_async() schedules them right away
                chain(
                    register_campaign_on_chain.s(campaign.id, seller_id_int),
                    save_onchain_action_info.s(
                        request.user.id,
                        campaign.id,
                        OnChainAction.CAMPAIGN_REGISTERED,
                        {},
                    ),
                ).apply_async()

                return Response(
                    {
                        "message": "Campaign created; on-chain registration queued.",
                        "campaign": response_serializer.data,
                    },
                    status=status.HTTP_202_ACCEPTED,
                )
        except Exception as e:
            logger.exception("Failed to create campaign")
            return Response(
                {"error": f"Failed to create campaign: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class WinnerSelectionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, campaign_id):
        user = request.user
        if user.user_type != "influencer":
            return Response({"error": "Only influencers may do this."}, status=403)

        # Fetch & authorize
        try:
            campaign = Campaign.objects.get(id=campaign_id, user=user)
        except Campaign.DoesNotExist:
            return Response({"error": "Not found/unauthorized."}, status=404)

        if campaign.winners_selected:
            return Response({"error": "Winners already selected."}, status=400)

        # Close campaign if open
        if not campaign.is_closed:
            campaign.is_closed = True
            campaign.closed_at = dj_timezone.now()
            campaign.save(update_fields=["is_closed", "closed_at"])

        # Compute sold vs goal
        specific = campaign.specific_campaign()
        if specific.campaign_type in ("ticket", "meet_greet"):
            sold = (
                specific.participations.aggregate(total=Sum("tickets_purchased"))[
                    "total"
                ]
                or 0
            )
            goal = specific.total_tickets
        elif specific.campaign_type == "media_selling":
            sold = (
                specific.participations.aggregate(total=Sum("media_purchased"))["total"]
                or 0
            )
            goal = specific.total_media
        else:
            sold, goal = 0, 0

        seller_id = int(user.user_id)

        # Refund vs release
        if campaign.refund_on_deadline and sold < goal:
            refund_all_holds_for_campaign_task.delay(campaign.id, seller_id)
            message = f"Campaign ended; sold {sold}/{goal} → refunds enqueued."
            winners = []
        else:
            release_all_holds_for_campaign_task.delay(campaign.id, seller_id)
            # pick winners per winner_slots + exclude_previous_winners
            winners = select_random_winners(campaign.id)
            campaign.winners_selected = True
            campaign.save(update_fields=["winners_selected"])
            message = f"Holds released; selected {len(winners)} winner(s)."

            # **start a conversation** between influencer & each winner
            for w in winners:
                get_or_create_winner_conversation(user, w)

        # Build response
        return Response(
            {
                "message": message,
                "winners": [
                    {"id": w.id, "username": w.username, "email": w.email}
                    for w in winners
                ],
            },
            status=200,
        )


def _compute_costs_and_tt(campaign, qty: int):
    # unit_cost can be ticket_cost or media_cost depending on type
    unit_cost = getattr(campaign, "ticket_cost", None) or getattr(
        campaign, "media_cost", None
    )
    cost_in_credits = int(qty * unit_cost)

    try:
        conversion_rate = contract.functions.conversionRate().call()
    except Exception:
        logger.exception("Failed to fetch conversionRate")
        raise

    spent_tt_whole = cost_in_credits // conversion_rate
    return cost_in_credits, spent_tt_whole


def perform_participation(
    *,
    fan,
    campaign_id: int,
    tickets_purchased: int | None = None,
    media_purchased: int | None = None,
    payment_method: str = "balance",
    order_id: str | None = None,
    tx_hash: str | None = None,
):
    """
    Validates via ParticipationSerializer, then performs the same side-effects as ParticipateInCampaignView.
    Returns: (participation, assigned_media_list)
    """

    # 1) Validate with your existing serializer so all rules are reused
    ser = ParticipationSerializer(
        data={
            "campaign": campaign_id,
            "tickets_purchased": tickets_purchased,
            "media_purchased": media_purchased,
            "payment_method": payment_method,
        },
        context={"fan": fan},
    )
    ser.is_valid(raise_exception=True)

    # 2) Use the campaign-specific instance (ticket/media/meet_greet)
    campaign = ser.validated_data["campaign"].specific_campaign()

    qty = (
        ser.validated_data.get("tickets_purchased")
        or ser.validated_data.get("media_purchased")
        or 0
    )
    
    is_free = ser.validated_data.get("is_free_entry", False) or ser.validated_data.get("payment_method") == "free"


    # 4) Persist everything atomically
    with transaction.atomic():
        participation = ser.save(fan=fan)
        
        if is_free:
            # ✅ nothing on-chain, no CreditSpend, no EscrowRecord
            assigned_media = []
            # and importantly, no media unlocks for free entries:
            return participation, assigned_media
        
        cost_in_credits, spent_tt_whole = _compute_costs_and_tt(campaign, qty)
        

        escrow = EscrowRecord.objects.create(
            user=fan,
            campaign=campaign,
            campaign_id=str(campaign.id),
            tt_amount=spent_tt_whole,
            credit_amount=cost_in_credits,
            status="held",
            tx_hash=tx_hash
            or "",  # you can store order_id too if your model has a field
            gas_cost_credits=0,
        )

        CreditSpend.objects.bulk_create(
            [
                CreditSpend(
                    user=fan,
                    campaign=campaign,
                    spend_type=CreditSpend.PARTICIPATION,
                    credits=cost_in_credits,
                    tt_amount=spent_tt_whole,
                ),
                CreditSpend(
                    user=fan,
                    campaign=campaign,
                    spend_type=CreditSpend.GAS_FEE,
                    credits=0,
                    description="Gas for tx",
                ),
            ]
        )

    # 5) Kick off the on-chain + accounting tasks (as you already do)
    chain(
        hold_for_campaign_on_chain.s(
            escrow.id,
            campaign.id,
            int(fan.user_id),
            spent_tt_whole,
            cost_in_credits,
        ),
        save_transaction_info.s(
            user_id=fan.id,
            campaign_id=campaign.id,
            tx_type=Transaction.SPEND,
            tt_amount=spent_tt_whole,
            credits_delta=cost_in_credits,
        ),
    ).apply_async()

    # 6) Grant media access if needed
    assigned_media = []
    if campaign.campaign_type == "media_selling":
        media_requested = ser.validated_data.get("media_purchased", 0)
        logger.info(
            "Assigning %d media files to user %s for campaign %s",
            media_requested,
            fan.username,
            campaign.id,
        )
        assigned_media = assign_media_to_user(campaign, fan, media_requested)

    return participation, assigned_media


class ParticipateInCampaignView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if user.user_type not in ["fan", "influencer"]:
            return Response({"error": "Only fans/influencers can participate."}, status=403)

        # Keep your serializer validation here (same as before)
        s = ParticipationSerializer(data=request.data, context={"fan": user})
        if not s.is_valid():
            return Response(s.errors, status=400)

        v = s.validated_data
        tickets = v.get("tickets_purchased")
        media = v.get("media_purchased")
        payment_method = v.get("payment_method")

        participation, assigned_media = perform_participation(
            fan=user,
            campaign_id=v["campaign"].id,
            tickets_purchased=tickets,
            media_purchased=media,
            payment_method=payment_method,
            # no order_id/tx_hash in this manual flow
        )

        media_info = [{"media_file_id": m.id} for m in assigned_media]

        return Response(
            {
                "message": "Participation successful",
                "participation": s.data,
                "assigned_media": media_info,
            },
            status=201,
        )


class CampaignUserMediaAccessListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MediaAccessSerializer

    def get_queryset(self):
        campaign_id = self.kwargs["campaign_id"]
        return MediaAccess.objects.filter(
            user=self.request.user,
            media_file__campaign_id=campaign_id,  # assuming relation
        )


class MediaDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, media_id):
        # 1) fetch & authz
        try:
            media = MediaFile.objects.get(pk=media_id)
        except MediaFile.DoesNotExist:
            return Response({"detail": "Not found."}, status=404)

        # built-in: fast EXISTS query via filter()
        if not MediaAccess.objects.filter(user=request.user, media_file=media).exists():
            return Response({"detail": "Forbidden."}, status=403)

        # 2) stream from S3 via boto3
        s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME,
        )
        obj = s3.get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=media.file.name
        )
        body = obj["Body"]  # this is a streaming file‐like

        # built-in: StreamingHttpResponse will iterate & chunk the body out
        resp = StreamingHttpResponse(
            streaming_content=body,
            content_type=obj.get("ContentType", "application/octet-stream"),
        )
        # built-in header for browser download
        resp["Content-Disposition"] = f'inline; filename="{media.file.name}"'
        return resp



def _ensure_prefixed(h: str) -> str:
    if not h:
        return ""
    return h if h.startswith("0x") else f"0x{h}"

class AutoParticipateConfirmView(APIView):
    """
    POST { campaign_id: int, entries: int, tx_hash: str }
    Waits (up to TX_MAX_WAIT) for the tx to confirm. On success, participates.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        s = AutoParticipateConfirmSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        v = s.validated_data

        tx_hash = _ensure_prefixed(v["tx_hash"])

        # Idempotency by (user, campaign, tx_hash)
        if EscrowRecord.objects.filter(
            user=request.user,
            campaign_id=v["campaign_id"],
            tx_hash=tx_hash,
        ).exists():
            return Response({"status": "already_processed"}, status=status.HTTP_200_OK)

        # -------- 1) Wait for on-chain confirmation (blocking up to timeout) --------
        try:
            # Best-effort: fast path (maybe it’s already mined)
            receipt = w3.eth.get_transaction_receipt(tx_hash)
        except TransactionNotFound:
            receipt = None

        if receipt is None:
            try:
                receipt = w3.eth.wait_for_transaction_receipt(
                    tx_hash, timeout=TX_MAX_WAIT, poll_latency=TX_POLL_LATENCY
                )
            except (TransactionNotFound, TimeExhausted):
                # Still pending after our wait window
                return Response({"status": "pending"}, status=status.HTTP_202_ACCEPTED)

        if receipt is None or getattr(receipt, "status", 0) != 1:
            # Mined but failed / reverted
            return Response({"status": "failed"}, status=status.HTTP_409_CONFLICT)

        # -------- 2) Determine campaign type and map entries accordingly --------
        try:
            # Your serializer in perform_participation resolves the generic campaign id.
            # We only need to know how to split 'entries' into tickets/media.
            campaign = Campaign.objects.get(id=v["campaign_id"]).specific_campaign()
            ctype = getattr(campaign, "campaign_type", None)  # 'ticket' | 'media_selling' | 'meet_greet'
        except Campaign.DoesNotExist:
            return Response({"detail": "Campaign not found"}, status=status.HTTP_404_NOT_FOUND)

        tickets = v["entries"] if ctype in ("ticket", "meet_greet") else None
        media   = v["entries"] if ctype == "media_selling" else None

        # -------- 3) Perform participation (atomic) --------
        try:
            participation, assigned_media = perform_participation(
                fan=request.user,
                campaign_id=v["campaign_id"],
                tickets_purchased=tickets,
                media_purchased=media,
                payment_method="balance",  # funds have been paid on-chain
                order_id=None,             # optional
                tx_hash=tx_hash,           # stored on EscrowRecord for dedupe
            )
        except Exception as e:
            return Response({"status": "error", "detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "status": "ok",
                "participation_id": participation.id,
                "assigned_media": [{"media_file_id": m.id} for m in assigned_media],
            },
            status=status.HTTP_200_OK,
        )

class ParticipantsView(APIView):
    permission_classes = []  # or use [AllowAny] if you want open access

    def get(self, request, campaign_id):
        try:
            campaign = Campaign.objects.get(id=campaign_id)
        except Campaign.DoesNotExist:
            return Response(
                {"error": "Campaign not found."}, status=status.HTTP_404_NOT_FOUND
            )

        # If the campaign type is media_selling, aggregate media_purchased; otherwise, aggregate tickets_purchased.
        if campaign.campaign_type == "media_selling":
            aggregated = (
                Participation.objects.filter(campaign=campaign)
                .values("fan")
                .annotate(
                    total_tickets_purchased=Sum("media_purchased"),
                    total_spending=Sum("amount"),
                )
            )
        else:
            aggregated = (
                Participation.objects.filter(campaign=campaign)
                .values("fan")
                .annotate(
                    total_tickets_purchased=Sum("tickets_purchased"),
                    total_spending=Sum("amount"),
                )
            )

        participants = []
        for record in aggregated:
            fan_id = record["fan"]
            user = User.objects.get(id=fan_id)
            user_data = UserCampaignSerializer(user, context={"request": request}).data
            profile_data = ProfileCampaignSerializer(
                user.profile, context={"request": request}
            ).data
            user_data["profile"] = profile_data

            participants.append(
                {
                    "user": user_data,
                    "total_tickets_purchased": record["total_tickets_purchased"] or 0,
                    "total_spending": str(record["total_spending"] or "0.00"),
                }
            )

        return Response({"participants": participants}, status=status.HTTP_200_OK)


class WinnersView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, campaign_id):
        try:
            campaign = Campaign.objects.get(id=campaign_id)

            # Ensure winners have been selected
            if not campaign.winners_selected:
                return Response(
                    {"error": "Winners have not been selected yet."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Fetch winners from CampaignWinner table
            winners = CampaignWinner.objects.filter(campaign=campaign)
            serializer = CampaignWinnerSerializer(winners, many=True)

            return Response({"winners": serializer.data}, status=status.HTTP_200_OK)
        except Campaign.DoesNotExist:
            return Response(
                {"error": "Campaign not found."}, status=status.HTTP_404_NOT_FOUND
            )


class ExploreCampaignsView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        now = dj_timezone.now()
        # Filter campaigns where the deadline is still in the future and the campaign is not closed.
        # Order them by creation date in descending order (newest first),
        # and then slice the QuerySet to get only the first 10 campaigns.
        active_campaigns = Campaign.objects.filter(
            deadline__gt=now, is_closed=False
        ).order_by("-created_at")[:10]

        # Serialize the active campaigns using the polymorphic serializer.
        serializer = PolymorphicCampaignDetailSerializer(
            active_campaigns, many=True, context={"request": request}
        )
        # Return the serialized data in the response.
        return Response({"campaigns": serializer.data}, status=status.HTTP_200_OK)


class InfluencerCampaignsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        if user.user_type != "influencer":
            return Response(
                {"error": "Only influencers can view their campaigns."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Fetch all campaigns created by the influencer (active + closed)
        campaigns = Campaign.objects.filter(user=user)
        serializer = InfluencerCampaignSerializer(
            campaigns, many=True, context={"request": request}
        )

        return Response({"campaigns": serializer.data}, status=status.HTTP_200_OK)


class InfluencerCampaignListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, influencer_id):
        # Ensure the user is an influencer
        try:
            influencer = User.objects.get(id=influencer_id, user_type="influencer")
        except User.DoesNotExist:
            return Response(
                {"error": "Influencer not found."}, status=status.HTTP_404_NOT_FOUND
            )

        # Fetch all campaigns created by the influencer
        campaigns = Campaign.objects.filter(user=influencer)
        serializer = PolymorphicCampaignDetailSerializer(
            campaigns, many=True, context={"request": request}
        )

        return Response(
            {
                "influencer": {
                    "id": influencer.id,
                    "username": influencer.username,
                    "email": influencer.email,
                },
                "campaigns": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class UpdateCampaignView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, campaign_id):
        user = request.user

        # Only influencers can edit campaigns.
        if user.user_type != "influencer":
            return Response(
                {"error": "Only influencers can edit campaigns."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Fetch the campaign using the base model.
        try:
            campaign = Campaign.objects.get(id=campaign_id, user=user)
        except Campaign.DoesNotExist:
            return Response(
                {"error": "Campaign not found or unauthorized access."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Prevent editing a closed campaign.
        if campaign.is_closed:
            return Response(
                {"error": "Closed campaigns cannot be edited."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Convert to the specific child instance.
        specific_instance = campaign.specific_campaign()

        # Select the appropriate update serializer based on campaign type.
        if campaign.campaign_type == "ticket":
            serializer = UpdateTicketCampaignSerializer(
                specific_instance, data=request.data, partial=True
            )
        elif campaign.campaign_type == "meet_greet":
            serializer = UpdateMeetAndGreetCampaignSerializer(
                specific_instance, data=request.data, partial=True
            )
        elif campaign.campaign_type == "media_selling":
            serializer = UpdateMediaSellingCampaignSerializer(
                specific_instance, data=request.data, partial=True
            )
        else:
            return Response(
                {"error": "Invalid campaign type."}, status=status.HTTP_400_BAD_REQUEST
            )

        if serializer.is_valid():
            serializer.save()
            # Refresh the instance from the database to pick up changes from the child table.
            specific_instance.refresh_from_db()

            # Use the polymorphic serializer to include type-specific fields.
            full_serializer = PolymorphicCampaignDetailSerializer(
                specific_instance, context={"request": request}
            )
            return Response(
                {
                    "message": "Campaign updated successfully.",
                    "campaign": full_serializer.data,
                },
                status=status.HTTP_200_OK,
            )
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CampaignDetailView(APIView):
    permission_classes = [AllowAny]  # No authentication required

    def get(self, request, campaign_id):
        try:
            campaign = Campaign.objects.get(id=campaign_id)
        except Campaign.DoesNotExist:
            return Response(
                {"error": "Campaign not found."}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = PolymorphicCampaignDetailSerializer(
            campaign, context={"request": request}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


class LikeCampaignView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, campaign_id):
        try:
            campaign = Campaign.objects.get(id=campaign_id)
        except Campaign.DoesNotExist:
            return Response({"error": "Campaign not found."}, status=404)

        user = request.user

        # Toggle like: if user already liked, remove; otherwise add.
        if campaign.likes.filter(id=user.id).exists():
            campaign.likes.remove(user)
            liked = False
        else:
            campaign.likes.add(user)
            liked = True

        return Response(
            {"liked": liked, "likes_count": campaign.likes.count()}, status=200
        )


class InfluencerWinnersView(APIView):
    """
    Returns all winners from campaigns created by a given influencer.
    """

    # You can choose to require authentication or allow any user.
    # For this example, we'll allow any.
    permission_classes = []  # or [AllowAny]

    def get(self, request, influencer_id):
        # Get the influencer user object.
        try:
            influencer = User.objects.get(id=influencer_id, user_type="influencer")
        except User.DoesNotExist:
            return Response(
                {"error": "Influencer not found."}, status=status.HTTP_404_NOT_FOUND
            )

        # Filter CampaignWinner objects for campaigns created by this influencer.
        winners = CampaignWinner.objects.filter(campaign__user=influencer)

        # Serialize the results. (You may want to extend CampaignWinnerSerializer to include more details.)
        serializer = CampaignWinnerSerializer(
            winners, many=True, context={"request": request}
        )
        return Response({"winners": serializer.data}, status=status.HTTP_200_OK)


class MediaFileSignedURLView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, access_id):
        access = get_object_or_404(MediaAccess, id=access_id, user=request.user)
        media_path = access.media_file.file.name  # S3 key path
        resource_url = f"https://{settings.CLOUDFRONT_DOMAIN}/{media_path}"
        signed_url = generate_cloudfront_signed_url(resource_url, expire_seconds=300)
        return Response({"signed_url": signed_url})


def _rsa_signer_loader(pem_str: str):
    key = load_pem_private_key(pem_str.encode("utf-8"), password=None)

    def _signer(message: bytes) -> bytes:
        return key.sign(message, padding.PKCS1v15(), hashes.SHA1())

    return _signer


from django.core.signing import TimestampSigner


def signed_media_token(media_id: int, user_id: int) -> str:
    payload = f"{media_id}:{user_id}"
    return TimestampSigner(salt="media-access").sign(payload)


class MediaDisplayView(APIView):
    permission_classes = [AllowAny]  # << was IsAuthenticated

    def get(self, request, media_id):
        user = request.user if request.user.is_authenticated else None

        # try bearer user first; otherwise fall back to signed token
        if not user:
            token = request.query_params.get("t")
            if not token:
                return Response({"detail": "Unauthorized."}, status=401)

            try:
                # use a fixed salt you also use when GENERATING the token
                raw = TimestampSigner(salt=SALT).unsign(token, max_age=TTL)
                mid, uid = raw.split(":", 1)  # "<media_id>:<user_id>"
                if str(media_id) != mid:
                    return Response({"detail": "Invalid token media id."}, status=403)
                user = User.objects.get(pk=uid)
            except (BadSignature, SignatureExpired, ValueError, User.DoesNotExist):
                return Response({"detail": "Unauthorized."}, status=401)

        media = get_object_or_404(MediaFile, pk=media_id)

        if not MediaAccess.objects.filter(user=user, media_file=media).exists():
            return Response({"detail": "Forbidden."}, status=403)

        object_key = media.file.name.lstrip("/")
        base_url = f"https://{settings.CLOUDFRONT_DOMAIN}/{object_key}"

        expire = dt.datetime.now(dt.timezone.utc) + timedelta(minutes=1)
        signer = CloudFrontSigner(
            settings.CLOUDFRONT_KEY_PAIR_ID,
            _rsa_signer_loader(settings.CLOUDFRONT_PRIVATE_KEY),
        )
        signed_url = signer.generate_presigned_url(base_url, date_less_than=expire)
        return HttpResponseRedirect(signed_url)


class MyMediaFilesView(ListAPIView):
    """
    GET /campaign/my/media/
    Returns MediaFile objects the authenticated user has access to,
    serialized by your existing MediaFileSerializer (so `file_url` is your
    /campaign/media-display/<id>?t=... route and `preview_url` is the thumb).
    """
    permission_classes = [IsAuthenticated]
    serializer_class = MediaFileSerializer

    def get_queryset(self):
        user = self.request.user
        qs = (
            MediaFile.objects
            # built-in: .filter() narrows rows; `accesses` is your reverse FK from MediaAccess
            .filter(accesses__user=user)
            # built-in: .select_related() joins a FK in the same query (useful if you want campaign fields later)
            .select_related("campaign")
            # built-in: .annotate() computes extra columns; here we compute the latest access timestamp
            .annotate(last_access=Max("accesses__created_at"))
            # built-in: .order_by() sorts; '-' means DESC (newest first)
            .order_by("-last_access", "-uploaded_at")
            # built-in: .distinct() removes duplicates if the join creates multiple rows
            .distinct()
        )

        # Optional filter: /campaign/my/media/?campaign=123
        cid = self.request.query_params.get("campaign")
        if cid:
            qs = qs.filter(campaign_id=cid)  # built-in: WHERE campaign_id = <cid>

        return qs

