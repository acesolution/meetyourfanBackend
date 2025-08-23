# compaign/urls.py
from django.urls import path
from .views import (
    CreateCampaignView,
    WinnerSelectionView, 
    ParticipateInCampaignView, 
    ParticipantsView, 
    WinnersView, 
    ExploreCampaignsView,
    InfluencerCampaignsView,
    InfluencerCampaignListView,
    UpdateCampaignView,
    CampaignDetailView,
    LikeCampaignView,
    InfluencerWinnersView,
    DashboardView,
    CampaignDashboardDetailView,
    FanAnalyticsView,
    CampaignUserMediaAccessListView,
    MediaDisplayView,  # Add this import if not present
    AutoParticipateConfirmView,
    MyMediaFilesView

)

app_name = "campaign"

urlpatterns = [
    path('create/campaign/', CreateCampaignView.as_view(), name='create-campaign'),
    path('select-winners/<int:campaign_id>/', WinnerSelectionView.as_view(), name='select-winners'),
    path('participate/', ParticipateInCampaignView.as_view(), name='participate-in-campaign'),
    path('participants/<int:campaign_id>/', ParticipantsView.as_view(), name='campaign-participants'),
    path('winners/<int:campaign_id>/', WinnersView.as_view(), name='campaign-winners'),
    path('explore/', ExploreCampaignsView.as_view(), name='explore-campaigns'),
    path('influencercampaigns/', InfluencerCampaignsView.as_view(), name='influencer-campaigns'),
    path('influencer/<int:influencer_id>/', InfluencerCampaignListView.as_view(), name='influencer-campaigns'),
    path('edit/campaign/<int:campaign_id>/', UpdateCampaignView.as_view(), name='edit-campaign'),
    path('campaign/<int:campaign_id>/', CampaignDetailView.as_view(), name='campaign-detail'),
    path('like/<int:campaign_id>/', LikeCampaignView.as_view(), name='campaign-like'),
    path('influencer/<int:influencer_id>/winners/', InfluencerWinnersView.as_view(), name='influencer-winners'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('dashboard/campaign/<int:campaign_id>/', CampaignDashboardDetailView.as_view(), name='campaign-dashboard-detail'),
    path('fan/analytics/', FanAnalyticsView.as_view(), name='fan-analytics'),
    path('view/<int:campaign_id>/media-access/', CampaignUserMediaAccessListView.as_view(), name='media-access'),
    path('media-display/<int:media_id>/', MediaDisplayView.as_view(), name='media-display'),
    path("auto-participate/confirm/", AutoParticipateConfirmView.as_view(), name="auto-participate-confirm"),
    path("my/media/", MyMediaFilesView.as_view(), name="my-media"),
]

