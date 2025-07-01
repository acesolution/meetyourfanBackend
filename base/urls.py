from django.urls import path
from base import views


urlpatterns = [
    path('', views.index, name='index'),
    path('save-email', views.save_email, name='save_email'),
    path('privacy-policy/', views.privacy_policy, name='privacy_policy'),
    path('terms-service/', views.terms_service, name='terms_service'),
    path('data-deletion/', views.data_deletion, name='data_deletion'),
]
