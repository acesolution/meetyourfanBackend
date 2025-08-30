# api/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.timezone import now
from datetime import timedelta
import random
import string
import uuid
from .utils import generate_user_id_int
from meetyourfanBackend.storage_backends import PublicMediaStorage, PrivateMediaStorage

# Create your models here.

def generate_user_id():
    return uuid.uuid4().hex

class CustomUser(AbstractUser):
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    USER_TYPE_CHOICES = [
        ('fan', 'Fan'),
        ('influencer', 'Influencer'),
    ]
    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES, default='fan')  # Add user type
    
    # Big‐enough to hold a 256‐bit integer
    user_id = models.CharField(
        max_length=256,
        unique=True,
        editable=False,
        default=generate_user_id_int
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']


class Profile(models.Model):
    STATUS_CHOICES = [
        ('public', 'Public'),
        ('private', 'Private'),
    ]
    
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='profile')
    name = models.CharField(max_length=100, blank=True, null=True)  # Add name field
    date_of_birth = models.DateField(blank=True, null=True)  # Add date of birth field
    bio = models.TextField(blank=True, null=True)
    profile_picture = models.ImageField(upload_to='media/public/profile_pictures/',storage=PublicMediaStorage(), blank=True, null=True)
    cover_photo = models.ImageField(upload_to='media/public/cover_photos/',storage=PublicMediaStorage(), blank=True, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='public')  # New field
    last_seen = models.DateTimeField(null=True, blank=True)
    is_online = models.BooleanField(default=False)
    cover_focal_x = models.FloatField(default=50)  # 0..100
    cover_focal_y = models.FloatField(default=50)  # 0..100
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s Profile"
    

class VerificationCode(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='verification_code')
    email_code = models.CharField(max_length=6, blank=True, null=True)
    phone_code = models.CharField(max_length=6, blank=True, null=True)
    email_verified = models.BooleanField(default=False)
    phone_verified = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    phone_sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default= now() + timedelta(minutes=10))
    
    # ─── withdrawal fields ─────────────────
    withdraw_email_code     = models.CharField(max_length=6, blank=True, null=True)
    withdraw_email_verified = models.BooleanField(default=False)
    withdraw_email_sent_at  = models.DateTimeField(blank=True, null=True)

    withdraw_phone_code     = models.CharField(max_length=6, blank=True, null=True)
    withdraw_phone_verified = models.BooleanField(default=False)
    withdraw_phone_sent_at  = models.DateTimeField(blank=True, null=True)
    withdraw_expires_at     = models.DateTimeField(blank=True, null=True)

    def generate_code(self):
        return ''.join(random.choices(string.digits, k=6))
    
class ReportGenericIssue(models.Model):
    # Optional: link the report to a user. Set null=True/blank=True if anonymous reports are allowed.
    user = models.ForeignKey(
        CustomUser, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        help_text="User who reported the issue"
    )
    # The category of the issue. You may use choices if you want to restrict categories.
    issue_category = models.CharField(
        max_length=100,
        help_text="Category of the issue (e.g., Bug, Feature Request, Other)"
    )
    # Detailed description of the issue.
    details = models.TextField(help_text="Detailed description of the issue")
    # Optional file attachment (can be an image or other file).
    attachment = models.FileField(
        upload_to='reported_issues/',
        null=True,
        blank=True,
        help_text="Optional attachment (image or file) related to the issue"
    )
    # Automatically set the timestamp when the report is created.
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Issue: {self.issue_category} reported by {self.user}"
    
    

class SocialMediaLink(models.Model):
    """
    A generic model to store a social media link for a user.
    This model supports multiple entries per user, each indicating
    the social media platform and its associated URL.
    """
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='social_links',
        help_text="The user who owns this social media link."
    )
    platform = models.CharField(
        max_length=50,
        help_text="Name of the social media platform (e.g., Instagram, TikTok, etc.)."
    )
    url = models.URLField(
        help_text="URL for the social media profile."
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="The date and time when this link was created."
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="The date and time when this link was last updated."
    )

    def __str__(self):
        return f"{self.platform} link for {self.user.username}"

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Social Media Link"
        verbose_name_plural = "Social Media Links"