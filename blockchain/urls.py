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
    WertWebhookView
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
]
