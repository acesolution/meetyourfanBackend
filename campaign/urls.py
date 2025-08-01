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
    FanAnalyticsView
)

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
]

