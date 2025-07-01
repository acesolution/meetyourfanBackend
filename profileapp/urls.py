#profileapp/urls.py

from django.urls import path
from profileapp.views import (
    BlockUserView, UnblockUserView,
    UnfollowUserView,FollowUserView,
    AcceptFollowRequestView, DeclineFollowRequestView,
    CancelFollowRequestView, FollowersListView, 
    BlockedUsersListView, FollowRequestsListView,
    FollowingListView, ReportUserView, RespondToMeetupView,
    ScheduleMeetupView, ReportIssueView
)

urlpatterns = [
    # Block and Unblock with user ID in the URL
    path('block/<int:blocked_user_id>/', BlockUserView.as_view(), name='block-user'),
    path('unblock/<int:blocked_user_id>/', UnblockUserView.as_view(), name='unblock-user'),

    # Follow and Unfollow with user ID in the URL
    path('unfollow/<int:user_id>/', UnfollowUserView.as_view(), name='unfollow-user'),

    # Follow request with receiver ID in the URL
    path('follow/<int:user_id>/', FollowUserView.as_view(), name='follow-request'),

    # Accept and Decline with sender ID in the URL
    path('accept-follow-request/<int:sender_id>/', AcceptFollowRequestView.as_view(), name='accept-follow-request'),
    path('decline-follow-request/<int:sender_id>/', DeclineFollowRequestView.as_view(), name='decline-follow-request'),

    # Cancel Follow Request with receiver ID in the URL
    path('cancel-follow-request/<int:receiver_id>/', CancelFollowRequestView.as_view(), name='cancel-follow-request'),
    
    path('all-followers/', FollowersListView.as_view(), name='followers-list'),
    path('all-blocked-users/', BlockedUsersListView.as_view(), name='blocked-users-list'),
    path('all-follow-requests/', FollowRequestsListView.as_view(), name='follow-requests-list'),
    
    path('all-followings/', FollowingListView.as_view(), name='following-list'),
    
    path('report-user/', ReportUserView.as_view(), name='report-user'),
    path('meetup/schedule/', ScheduleMeetupView.as_view(), name='schedule-meetup'),
    path('meetup/respond/<int:meetup_id>/', RespondToMeetupView.as_view(), name='respond-meetup'),
    
    path('report-genric-issue/', ReportIssueView.as_view(), name='report-genric-issue'),
]
