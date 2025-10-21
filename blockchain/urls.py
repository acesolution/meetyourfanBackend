# blockchain/urls.py

from django.urls import path
from .views import (
    RegisterUserView,
    DepositView,
    SetUserWalletView,
    MyBalancesView,
    GetUserWalletView,
    MyLatestSnapshotView,
    WithdrawView,
    WithdrawVerifyRequestCodeView,
    WithdrawVerifyCodeView,
    WithdrawUpdateEmailView,
    ConfirmDepositView,
    WertWebhookView,
    ConversionRateView,
    UserTransactionsView,
    ReportTransactionIssueView,
    InfluencerEarningsView,
    FanSpendingsView,
    DailyWithdrawUsageView,
    GuestInitDepositView,
    GuestClaimView,
    GuestClaimPreviewView,
)

app_name = "blockchain"

urlpatterns = [
    path('register/',        RegisterUserView.as_view(),   name='register_user'),
    path('deposit/',         DepositView.as_view(),        name='deposit'),
    path('set-wallet/',      SetUserWalletView.as_view(),  name='set_user_wallet'),
    path('balances/me/',  MyBalancesView.as_view(),      name='my_balances'),
    path('balances/me/latest/', MyLatestSnapshotView.as_view(), name='my_latest_snapshot'),
    path('get-wallet/',   GetUserWalletView.as_view(),   name='get_user_wallet'),
    path("withdraw/request-code/", WithdrawVerifyRequestCodeView.as_view()),
    path("withdraw/verify-code/",  WithdrawVerifyCodeView.as_view()),
    path("withdraw/",              WithdrawView.as_view()),
    path( "withdraw/update-email/", WithdrawUpdateEmailView.as_view(), name="withdraw-update-email"),
    path('confirm-deposit/', ConfirmDepositView.as_view(), name='confirm-deposit'),
    path('webhooks/wert/', WertWebhookView.as_view(), name='wert-webhook'),
    path('conversion-rate/', ConversionRateView.as_view(), name='conversion-rate'),
    path('user-transactions/', UserTransactionsView.as_view(), name='user-transactions'),
    path("report-transaction-issue/", ReportTransactionIssueView.as_view(), name="report-transaction-issue"),
    path("influencer-earnings/", InfluencerEarningsView.as_view(), name="influencer-earnings"),
    path("fan-spendings/", FanSpendingsView.as_view(), name="fan-spendings"),
    path("withdraw/usage/", DailyWithdrawUsageView.as_view()),
    path("guest/init-deposit/", GuestInitDepositView.as_view(), name="guest-init-deposit"),
    path("guest/claim/",        GuestClaimView.as_view(),      name="guest-claim"),
    path("guest/claim/preview/", GuestClaimPreviewView.as_view()),

]
