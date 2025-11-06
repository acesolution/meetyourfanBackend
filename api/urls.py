#api/urls.py
from django.urls import path
from .views import (
    RegisterView,
    LoginView,
    ResetPasswordAPIView,
    CheckUsernameAvailabilityView,
    SendVerificationCodeView,
    VerifyCodeView,
    ResendVerificationCodeView,
    EditContactInfoView,
    LogoutView,
    UserProfileUpdateView,
    ProfileView,
    InfluencersView,
    FansView,
    InfluencerDetailView, 
    UpdateProfileStatusView,
    SubscribeEmailAPIView,
    TestResetPasswordView,
    InstagramCallbackView,
    InstagramConnectView,
    FanDetailView,
    UserDashboardAnalyticsView,
    ProfileImageUploadView,
    SocialMediaLinkListCreateAPIView, 
    SocialMediaLinkDetailAPIView,
    UpdateEmailView,
    CurrentUserView,
    GuestCampaignPurchaseView,
    DeleteCoverPhotoView,
    DeleteProfilePictureView,
    CoverFocalUpdateView,
    UpdateUsernameView,
    UsernameResetByTokenView,
)

from rest_framework_simplejwt.views import TokenRefreshView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("users/me/", CurrentUserView.as_view(), name="current-user"),
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/reset-password/', ResetPasswordAPIView.as_view(), name='resetPWD'),
    path('auth/check-username/', CheckUsernameAvailabilityView.as_view(), name='check-username'),
    path('auth/send-code/', SendVerificationCodeView.as_view(), name='send-code'),
    path('auth/verify-code/', VerifyCodeView.as_view(), name='verify-code'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/resend-code/', ResendVerificationCodeView.as_view(), name='resend-code'),
    path('auth/edit-contact/', EditContactInfoView.as_view(), name='edit-contact'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    path('auth/update-email/', UpdateEmailView.as_view(), name='update-email'),
    path('update/user-profile/', UserProfileUpdateView.as_view(), name='user-profile-update'),
    path('profile/', ProfileView.as_view(), name='profile'),
    path('influencers/', InfluencersView.as_view(), name='influencers-list'),
    path('fans/', FansView.as_view(), name='fans-list'),
    path('influencer/<int:influencer_id>/', InfluencerDetailView.as_view(), name='influencer-detail'),
    path('profile/status/', UpdateProfileStatusView.as_view(), name='update-profile-status'),
    path('profile/upload-images/', ProfileImageUploadView.as_view(), name='update-profile-images'),
    path("profile/picture/", DeleteProfilePictureView.as_view()),
    path("profile/cover/",   DeleteCoverPhotoView.as_view()),
    # Instagram integration
    path('instagram/connect/', InstagramConnectView.as_view(), name='instagram-connect'),
    path('instagram/callback/', InstagramCallbackView.as_view(), name='instagram-callback'),

    # Testing reset password view (for front-end testing)
    path('test/reset-password/<uidb64>/<token>/', TestResetPasswordView.as_view(), name='test-reset-password'),

    # Subscribe email endpoint
    path('subscribe/', SubscribeEmailAPIView.as_view(), name='subscribe-email'),
    
    path('fan/<int:fan_id>/', FanDetailView.as_view(), name='fan-detail'),
    path('user/profile/', UserDashboardAnalyticsView.as_view(), name='dashboard-analytics'),
    
    path('social-links/', SocialMediaLinkListCreateAPIView.as_view(), name='social-links-list'),
    path('social-links/<int:pk>/', SocialMediaLinkDetailAPIView.as_view(), name='social-links-detail'),
    path('guest/campaign/purchase/', GuestCampaignPurchaseView.as_view(), name='guest-campaign-purchase'),
    path('profile/cover-focal/', CoverFocalUpdateView.as_view(), name='guest-campaign-purchase'),
    path("profile/update-username/", UpdateUsernameView.as_view(), name="profile-update-username",),
    path("profile/username-reset/", UsernameResetByTokenView.as_view(), name="username_reset"),
    
]
