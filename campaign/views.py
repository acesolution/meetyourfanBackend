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
    UserCampaignSerializer
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
    PurchasedMedia,
    CreditSpend,
    EscrowRecord
)
from django.core.mail import send_mail
from django.utils.timezone import now
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Sum, Count, Q
from decimal import Decimal
from django.conf import settings
import logging
from blockchain.utils import w3, contract
from web3.exceptions import ContractLogicError, TimeExhausted
import time
from campaign.utils import select_random_winners, get_or_create_winner_conversation
from blockchain.tasks import register_campaign_on_chain, hold_for_campaign_on_chain
from django.db import transaction
from blockchain.tasks import release_all_holds_for_campaign_task, refund_all_holds_for_campaign_task, save_onchain_action_info
from celery import chain
from blockchain.models import OnChainAction

User = get_user_model()

logger = logging.getLogger(__name__)


def wait_for_tx_receipt(tx_hash: str, poll_interval: float = 2.0, timeout: float = 120.0):
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

class DashboardView(APIView):
    """
    Returns dashboard data for the authenticated influencer:
      - Active campaigns
      - Total earning (sum of participation amounts)
      - Total participation count
      - Total tickets purchased (for ticket and meet_greet campaigns)
      - Total winners across all campaigns
      - Placeholder for performance data (for graph)
    """
    def get(self, request):
        # Check that the user is an influencer
        if request.user.user_type != 'influencer':
            return Response({'error': 'Only influencers can access the dashboard.'}, status=status.HTTP_403_FORBIDDEN)

        now_time = timezone.now()
        
        # Active campaigns: campaigns that are not closed and whose deadline is in the future.
        active_campaigns_qs = Campaign.objects.filter(
            user=request.user,
            is_closed=False,
            deadline__gte=now_time
        )
        active_campaigns_count = active_campaigns_qs.count()

        # Total earning: Sum of amounts from participations for all campaigns created by the influencer.
        earning_agg = Participation.objects.filter(
            campaign__user=request.user
        ).aggregate(total_earning=Sum('amount'))
        total_earning = earning_agg['total_earning'] or 0

        # Total participation count: Total number of participation records
        total_participants = Participation.objects.filter(
            campaign__user=request.user
        ).count()

        # Total tickets purchased (for ticket or meet_greet campaigns)
        tickets_agg = Participation.objects.filter(
            campaign__user=request.user,
            campaign__campaign_type__in=['ticket', 'meet_greet']
        ).aggregate(total_tickets=Sum('tickets_purchased'))
        total_tickets = tickets_agg['total_tickets'] or 0
        
        # Total campaigns: all campaigns created by the influencer.
        total_campaigns = Campaign.objects.filter(user=request.user).count()

        # Total winners count: Count of winners across campaigns created by the influencer.
        total_winners = CampaignWinner.objects.filter(
            campaign__user=request.user
        ).count()
        
        # Total likes: Aggregate the count of likes across all campaigns created by the influencer.
        likes_agg = Campaign.objects.filter(user=request.user).aggregate(total_likes=Count('likes'))
        total_likes = likes_agg.get('total_likes') or 0

        # Placeholder for performance data (e.g., campaign performance graph).
        performance_data = {}  # You can add your logic here later.

        data = {
            "total_active_campaigns": active_campaigns_count,
            "total_campaigns": total_campaigns,
            "total_earning": total_earning,
            "total_likes": total_likes,
            "total_participants": total_participants,
            "total_tickets": total_tickets,
            "total_winners": total_winners,
            "performance_data": performance_data
        }
        return Response(data, status=status.HTTP_200_OK)
    
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
        if request.user.user_type != 'fan':
            return Response({'error': 'Only fans can access this analytics endpoint.'}, status=status.HTTP_403_FORBIDDEN)

        # Total distinct campaigns participated in
        total_campaigns_participated = Participation.objects.filter(
            fan=request.user
        ).values('campaign').distinct().count()

        # Total participation count (all participation records)
        total_participation_count = Participation.objects.filter(
            fan=request.user
        ).count()

        # Total spendings
        spending_agg = Participation.objects.filter(
            fan=request.user
        ).aggregate(total_spending=Sum('amount'))
        total_spending = spending_agg['total_spending'] or 0

        # Total tickets purchased (only for ticket and meet & greet campaigns)
        tickets_agg = Participation.objects.filter(
            fan=request.user,
            campaign__campaign_type__in=['ticket', 'meet_greet']
        ).aggregate(total_tickets=Sum('tickets_purchased'))
        total_tickets = tickets_agg['total_tickets'] or 0

        # Total winnings (count of distinct campaigns won by this fan)
        total_winnings = CampaignWinner.objects.filter(
            fan=request.user
        ).count()

        # Placeholder for additional performance data
        performance_data = {}

        data = {
            'total_campaigns_participated': total_campaigns_participated,
            'total_participation_count': total_participation_count,
            'total_spending': total_spending,
            'total_tickets': total_tickets,
            'total_winnings': total_winnings,
            'performance_data': performance_data
        }

        return Response(data, status=status.HTTP_200_OK)
    
class CampaignDashboardDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, campaign_id):
        # 1) Ensure the authenticated user owns this campaign
        try:
            campaign = Campaign.objects.get(id=campaign_id, user=request.user)
        except Campaign.DoesNotExist:
            return Response(
                {'error': 'Campaign not found or you are not the owner.'},
                status=status.HTTP_404_NOT_FOUND
            )

        # 2) Distinct participant count
        total_participants = (
            campaign.participations
                    .values('fan')       # group by fan
                    .distinct()          # remove duplicates
                    .count()
        )

        # 3) Total earnings
        agg = campaign.participations.aggregate(total_earning=Sum('amount'))
        total_earning = agg['total_earning'] or 0

        # 4) Total likes
        total_likes = campaign.likes.count()

        # 5) Total tickets sold (if applicable)
        total_tickets = 0
        if campaign.campaign_type in ['ticket', 'meet_greet']:
            agg = campaign.participations.aggregate(total_tickets=Sum('tickets_purchased'))
            total_tickets = agg['total_tickets'] or 0

        # 6) On-chain held amounts
        try:
            # note: both mappings use string campaignId
            tt_on_hold      = contract.functions.totalHeldTT(str(campaign.id)).call({'from': OWNER})
            credits_on_hold = contract.functions.totalHeldCredits(str(campaign.id)).call({'from': OWNER})
        except Exception:
            logger.exception("Failed to fetch on-chain hold for campaign %s", campaign.id)
            tt_on_hold = 0
            credits_on_hold = 0

        # 7) Build response
        data = {
            "campaign_id":      campaign.id,
            "title":            campaign.title,
            "total_participants": total_participants,
            "total_earning":      total_earning,
            "total_likes":        total_likes,
            "total_tickets_sold": total_tickets,
            "tt_on_hold":         tt_on_hold,
            "credits_on_hold":    credits_on_hold,
            "is_closed":         campaign.is_closed,
        }

        return Response(data, status=status.HTTP_200_OK)

class CreateCampaignView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        if user.user_type != 'influencer':
            return Response({'error': 'Only influencers can create campaigns.'}, status=status.HTTP_403_FORBIDDEN)

        # 1) Validate & save to DB
        serializer = PolymorphicCampaignSerializer(data=request.data, context={'request': request} )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Save the campaign (so we get campaign.id)
        campaign = serializer.save(user=user)

        # If it’s a media_selling campaign, handle uploaded files as before:
        if campaign.campaign_type == 'media_selling':
            files = request.FILES.getlist('media_files')
            for file in files:
                MediaFile.objects.create(campaign=campaign, file=file)
            campaign.ticket_limit_per_fan = len(files)
            campaign.save(update_fields=['ticket_limit_per_fan'])
            response_serializer = MediaSellingCampaignSerializer(campaign, context={'request': request})
        elif isinstance(campaign, TicketCampaign):
            response_serializer = TicketCampaignSerializer(campaign, context={'request': request})
        elif isinstance(campaign, MeetAndGreetCampaign):
            response_serializer = MeetAndGreetCampaignSerializer(campaign, context={'request': request})
        else:
            # If you add more types later, handle them here
            return Response({'error': 'Unknown campaign type.'}, status=status.HTTP_400_BAD_REQUEST)

        # ──────────────────────────────────────────────────────────────────────────────
        # 2) Register on-chain: build & send a “createCampaign” (or “registerCampaign”) tx
        # ──────────────────────────────────────────────────────────────────────────────

        try:
            seller_id_int = int(request.user.user_id)
        except (TypeError, ValueError):
            return Response(
                {'error': f'Invalid on-chain seller ID: {request.user.user_id!r}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        chain(
            register_campaign_on_chain.s(campaign.id, seller_id_int),
            save_onchain_action_info.s(request.user.id, campaign.id,OnChainAction.CAMPAIGN_REGISTERED, {})  
            # built‑in: .s() makes an “immutable signature” so the chain passes tx_hash into the next
        ).apply_async()  # built‑in: schedule the whole chain immediately

        return Response({
            'message':  'Campaign created; on-chain registration queued.',
            'campaign': response_serializer.data
        }, status=status.HTTP_202_ACCEPTED)


class WinnerSelectionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, campaign_id):
        user = request.user
        if user.user_type != 'influencer':
            return Response({'error': 'Only influencers may do this.'}, status=403)

        # Fetch & authorize
        try:
            campaign = Campaign.objects.get(id=campaign_id, user=user)
        except Campaign.DoesNotExist:
            return Response({'error': 'Not found/unauthorized.'}, status=404)

        if campaign.winners_selected:
            return Response({'error': 'Winners already selected.'}, status=400)

        # Close campaign if open
        if not campaign.is_closed:
            campaign.is_closed = True
            campaign.closed_at = timezone.now()
            campaign.save(update_fields=['is_closed','closed_at'])

        # Compute sold vs goal
        specific = campaign.specific_campaign()
        if specific.campaign_type in ('ticket','meet_greet'):
            sold = specific.participations.aggregate(total=Sum('tickets_purchased'))['total'] or 0
            goal = specific.total_tickets
        elif specific.campaign_type == 'media_selling':
            sold = specific.participations.aggregate(total=Sum('media_purchased'))['total'] or 0
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
            campaign.save(update_fields=['winners_selected'])
            message = f"Holds released; selected {len(winners)} winner(s)."

            # **start a conversation** between influencer & each winner
            for w in winners:
                get_or_create_winner_conversation(user, w)

        # Build response
        return Response({
            'message': message,
            'winners': [
                {'id': w.id, 'username': w.username, 'email': w.email}
                for w in winners
            ]
        }, status=200)


class ParticipateInCampaignView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        # 1) Basic perms check
        if user.user_type not in ["fan", "influencer"]:
            return Response({"error": "Only fans/influencers can participate."},
                            status=status.HTTP_403_FORBIDDEN)

        serializer = ParticipationSerializer(data=request.data, context={"fan": user})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        campaign = serializer.validated_data["campaign"].specific_campaign()
        if user.user_type == "influencer" and campaign.user == user:
            return Response({"error": "Campaign creators cannot participate in their own campaigns."},
                            status=status.HTTP_403_FORBIDDEN)

        # 2) Compute logical cost in credits
        qty = (
            serializer.validated_data.get("tickets_purchased")
            or serializer.validated_data.get("media_purchased")
            or 0
        )
        unit_cost = getattr(campaign, "ticket_cost", None) or getattr(campaign, "media_cost", None)
        cost_in_credits = int(qty * unit_cost)
        
        # 3) Fetch conversionRate from the on‐chain contract
        try:
            conversion_rate = contract.functions.conversionRate().call()  # e.g. R = 100
        except Exception:
            logger.exception("Failed to fetch conversionRate")
            return Response({"error": "Could not fetch conversion rate"}, status=502)

        # 5) Compute how many whole TT tokens to spend
        spent_tt_whole = cost_in_credits // conversion_rate

        # 10) Persist participation + gas‐deduction record
        try:
            participation = serializer.save(fan=user)
            escrow = EscrowRecord.objects.create(
                user=user,
                campaign=campaign,
                campaign_id=str(campaign.id),
                tt_amount=spent_tt_whole,
                credit_amount=cost_in_credits,
                status="held",
                tx_hash="",
                gas_cost_credits=0,
            )
            CreditSpend.objects.bulk_create(
                [
                    CreditSpend(
                        user=user,
                        campaign=campaign,
                        spend_type=CreditSpend.PARTICIPATION,
                        credits=cost_in_credits,
                        tt_amount=spent_tt_whole,
                    ),
                    CreditSpend(
                        user=user,
                        campaign=campaign,
                        spend_type=CreditSpend.GAS_FEE,
                        credits=0,
                        description=f"Gas for tx"
                    ),
                ]
            )
            
            def enqueue_hold():
                logger.info(f"📮 Enqueuing on-chain hold for escrow {escrow.id}")
                result = hold_for_campaign_on_chain.delay(
                    escrow.id,
                    campaign.id,
                    int(request.user.user_id),
                    spent_tt_whole,
                    cost_in_credits,
                )
                logger.info(f"🚀 Task ID: {result.id}")

            transaction.on_commit(enqueue_hold)

        except Exception:
            logger.exception("DB persistence failed")
            return Response({"error": "Server error while recording participation"}, status=500)

        return Response(
            {
                "message": "Participation successful",
                
                "participation": serializer.data,
            },
            status=201,
        )


class ParticipantsView(APIView):
    permission_classes = []  # or use [AllowAny] if you want open access
    
    def get(self, request, campaign_id):
        try:
            campaign = Campaign.objects.get(id=campaign_id)
        except Campaign.DoesNotExist:
            return Response({"error": "Campaign not found."}, status=status.HTTP_404_NOT_FOUND)
        
        # If the campaign type is media_selling, aggregate media_purchased; otherwise, aggregate tickets_purchased.
        if campaign.campaign_type == "media_selling":
            aggregated = (
                Participation.objects.filter(campaign=campaign)
                .values("fan")
                .annotate(
                    total_tickets_purchased=Sum("media_purchased"),
                    total_spending=Sum("amount")
                )
            )
        else:
            aggregated = (
                Participation.objects.filter(campaign=campaign)
                .values("fan")
                .annotate(
                    total_tickets_purchased=Sum("tickets_purchased"),
                    total_spending=Sum("amount")
                )
            )
        
        participants = []
        for record in aggregated:
            fan_id = record["fan"]
            user = User.objects.get(id=fan_id)
            user_data = UserCampaignSerializer(user, context={"request": request}).data
            profile_data = ProfileCampaignSerializer(user.profile, context={"request": request}).data
            user_data["profile"] = profile_data
            
            participants.append({
                "user": user_data,
                "total_tickets_purchased": record["total_tickets_purchased"] or 0,
                "total_spending": str(record["total_spending"] or "0.00")
            })
        
        return Response({"participants": participants}, status=status.HTTP_200_OK)
        
class WinnersView(APIView):
    permission_classes = [AllowAny]
    
    def get(self, request, campaign_id):
        try:
            campaign = Campaign.objects.get(id=campaign_id)

            # Ensure winners have been selected
            if not campaign.winners_selected:
                return Response({'error': 'Winners have not been selected yet.'}, status=status.HTTP_400_BAD_REQUEST)

            # Fetch winners from CampaignWinner table
            winners = CampaignWinner.objects.filter(campaign=campaign)
            serializer = CampaignWinnerSerializer(winners, many=True)

            return Response({'winners': serializer.data}, status=status.HTTP_200_OK)
        except Campaign.DoesNotExist:
            return Response({'error': 'Campaign not found.'}, status=status.HTTP_404_NOT_FOUND)

class ExploreCampaignsView(APIView):
    permission_classes = [AllowAny]
    
    def get(self, request):
        now = timezone.now()
        # Filter campaigns where the deadline is still in the future and the campaign is not closed.
        # Order them by creation date in descending order (newest first),
        # and then slice the QuerySet to get only the first 10 campaigns.
        active_campaigns = Campaign.objects.filter(
            deadline__gt=now, 
            is_closed=False
        ).order_by('-created_at')[:10]
        
        # Serialize the active campaigns using the polymorphic serializer.
        serializer = PolymorphicCampaignDetailSerializer(active_campaigns, many=True, context={'request': request})
        # Return the serialized data in the response.
        return Response({'campaigns': serializer.data}, status=status.HTTP_200_OK)
    
class InfluencerCampaignsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        if user.user_type != 'influencer':
            return Response({'error': 'Only influencers can view their campaigns.'}, status=status.HTTP_403_FORBIDDEN)

        # Fetch all campaigns created by the influencer (active + closed)
        campaigns = Campaign.objects.filter(user=user)
        serializer = InfluencerCampaignSerializer(campaigns, many=True, context={'request': request})

        return Response({'campaigns': serializer.data}, status=status.HTTP_200_OK)

class InfluencerCampaignListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, influencer_id):
        # Ensure the user is an influencer
        try:
            influencer = User.objects.get(id=influencer_id, user_type='influencer')
        except User.DoesNotExist:
            return Response({'error': 'Influencer not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Fetch all campaigns created by the influencer
        campaigns = Campaign.objects.filter(user=influencer)
        serializer = PolymorphicCampaignDetailSerializer(campaigns, many=True, context={'request': request})

        return Response({
            'influencer': {
                'id': influencer.id,
                'username': influencer.username,
                'email': influencer.email
            },
            'campaigns': serializer.data
        }, status=status.HTTP_200_OK)

class UpdateCampaignView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, campaign_id):
        user = request.user

        # Only influencers can edit campaigns.
        if user.user_type != 'influencer':
            return Response({'error': 'Only influencers can edit campaigns.'}, status=status.HTTP_403_FORBIDDEN)

        # Fetch the campaign using the base model.
        try:
            campaign = Campaign.objects.get(id=campaign_id, user=user)
        except Campaign.DoesNotExist:
            return Response({'error': 'Campaign not found or unauthorized access.'}, status=status.HTTP_404_NOT_FOUND)

        # Prevent editing a closed campaign.
        if campaign.is_closed:
            return Response({'error': 'Closed campaigns cannot be edited.'}, status=status.HTTP_400_BAD_REQUEST)

        # Convert to the specific child instance.
        specific_instance = campaign.specific_campaign()

        # Select the appropriate update serializer based on campaign type.
        if campaign.campaign_type == 'ticket':
            serializer = UpdateTicketCampaignSerializer(specific_instance, data=request.data, partial=True)
        elif campaign.campaign_type == 'meet_greet':
            serializer = UpdateMeetAndGreetCampaignSerializer(specific_instance, data=request.data, partial=True)
        elif campaign.campaign_type == 'media_selling':
            serializer = UpdateMediaSellingCampaignSerializer(specific_instance, data=request.data, partial=True)
        else:
            return Response({'error': 'Invalid campaign type.'}, status=status.HTTP_400_BAD_REQUEST)

        if serializer.is_valid():
            serializer.save()
            # Refresh the instance from the database to pick up changes from the child table.
            specific_instance.refresh_from_db()

            # Use the polymorphic serializer to include type-specific fields.
            full_serializer = PolymorphicCampaignDetailSerializer(specific_instance, context={'request': request})
            return Response({
                'message': 'Campaign updated successfully.',
                'campaign': full_serializer.data
            }, status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class CampaignDetailView(APIView):
    permission_classes = [AllowAny]  # No authentication required

    def get(self, request, campaign_id):
        try:
            campaign = Campaign.objects.get(id=campaign_id)
        except Campaign.DoesNotExist:
            return Response({'error': 'Campaign not found.'}, status=status.HTTP_404_NOT_FOUND)
        
        serializer = PolymorphicCampaignDetailSerializer(campaign, context={'request': request})
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

        return Response({
            "liked": liked,
            "likes_count": campaign.likes.count()
        }, status=200)
             
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
            influencer = User.objects.get(id=influencer_id, user_type='influencer')
        except User.DoesNotExist:
            return Response({'error': 'Influencer not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Filter CampaignWinner objects for campaigns created by this influencer.
        winners = CampaignWinner.objects.filter(campaign__user=influencer)
        
        # Serialize the results. (You may want to extend CampaignWinnerSerializer to include more details.)
        serializer = CampaignWinnerSerializer(winners, many=True, context={'request': request})
        return Response({'winners': serializer.data}, status=status.HTTP_200_OK)