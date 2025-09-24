"""
URL configuration for meetyourfanBackend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from django.views.generic.base import TemplateView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
    path('', include('base.urls')),
    path('profileapp/', include('profileapp.urls')),
    path('campaign/', include('campaign.urls')),
    path('api/messages/', include('messagesapp.urls')),
    path('api/notifications/', include('notificationsapp.urls')),
    path('api/social-logins/', include('sociallogins.urls')),
    path('api/blockchain/', include('blockchain.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
