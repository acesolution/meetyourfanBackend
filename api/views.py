# api/views.py

from django.shortcuts import render
from rest_framework import generics
from rest_framework.renderers import JSONRenderer
from api.models import Profile, VerificationCode, SocialMediaLink, UsernameResetToken
from rest_framework.views import APIView
from rest_framework.response import Response
from django.template.loader import render_to_string
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny
from django.conf import settings
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import authenticate, get_user_model
from django.core.mail import send_mail
from api.serializers import (
    RegisterSerializer, 
    UserSerializer, 
    UserProfileUpdateSerializer, 
    ProfileSerializer,
    InfluencerSerializer,
    FanSerializer,
    ProfileStatusSerializer,
    EmailSerializer,
    AllUserSerializer,
    SocialMediaLinkSerializer,
    UserUserIdSerializer,
    ProfileImageSerializer
)
from django.utils import timezone
from datetime import timedelta
import re
from twilio.rest import Client  # Replace with your SMS provider
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
import requests
from base.models import Email
from profileapp.models import Follower
from campaign.models import Campaign, Participation, CampaignWinner
from campaign.serializers import BaseCampaignSerializer
from django.db.models import Count
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
import logging
from api.utils import generate_unique_username_for_user
import secrets
from django.contrib.auth.password_validation import validate_password
from django.utils.encoding import force_str
from api.services.account_deletion import soft_delete_user

User = get_user_model()
logger = logging.getLogger(__name__)
class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # `request.user` is your CustomUser
        serializer = UserUserIdSerializer(request.user, context={'request': request})
        return Response(serializer.data)

class RegisterView(APIView):
    permission_classes = [AllowAny] 
    authentication_classes = []
    
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()

            # Generate JWT tokens for the user.
            refresh = RefreshToken.for_user(user)

            # Create or get the VerificationCode instance for the user.
            from api.models import VerificationCode  # Ensure correct import
            verification, created = VerificationCode.objects.get_or_create(user=user)

            # Generate a new verification code and update the record.
            code = verification.generate_code()
            verification.email_code = code
            verification.email_verified = False  # Reset verification flag if needed
            verification.expires_at = timezone.now() + timedelta(minutes=10)
            verification.email_sent_at = timezone.now()  # Record when the code was sent
            verification.save()
            
            # Render the HTML email template with context.
            context = {
                "username": user.username,
                "verification_code": code
            }
            html_message = render_to_string("verify_email.html", context)
            plain_message = f"Thank you for registering. Your verification code is: {code}"


            # Send the verification email.
            try:
                # built-in function send_mail() sends an email using the configured SMTP backend.
                send_mail(
                    subject="Verify Your Email Address",
                    message=plain_message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    fail_silently=False,
                    html_message=html_message,
                )
            except Exception as e:
                # Log the error if needed and return a response indicating the email wasn't sent.
                # You might also consider retrying or storing the error for later review.
                return Response(
                    {"error": f"User registered but failed to send verification email. Error: {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            # Serialize user data to include in the response.
            user_data = UserSerializer(user).data

            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'user': user_data,
                'message': "User registered successfully. A verification code has been sent to your email."
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = request.user.profile
        serializer = ProfileSerializer(profile)
        return Response(serializer.data, status=200)

    def put(self, request):
        profile = request.user.profile
        serializer = ProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    
class LoginView(APIView):
    permission_classes = [AllowAny] 
    authentication_classes = []
    
    def post(self, request):
        identifier = request.data.get('identifier')
        password = request.data.get('password')
        
        if not identifier or not password:
            return Response({'error': 'email/username and password are required.'},
                            status=status.HTTP_400_BAD_REQUEST)
        
        # Check if the identifier is a valid email
        try:
            validate_email(identifier)
            # If no exception, it's a valid email format.
            user = authenticate(request, email=identifier, password=password)
        except ValidationError:
            # Otherwise, treat it as a username.
            user = authenticate(request, username=identifier, password=password)
        
        if user:
            refresh = RefreshToken.for_user(user)
            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'user': UserSerializer(user).data,
            }, status=status.HTTP_200_OK)
        
        return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
    
    
    
    
class ResetPasswordAPIView(APIView):
    permission_classes = [AllowAny] 
    authentication_classes = []
    
    def post(self, request):
        email = request.data.get("email")
        if not email:
            return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Instead of returning 404, return a message indicating that the email is not registered.
            return Response(
                {"error": "A password reset link cannot be sent because this email is not registered."},
                status=status.HTTP_200_OK
            )

        # Generate token and uid using Django's built-in functionality.
        token_generator = PasswordResetTokenGenerator()
        token = token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        
        # Construct a reset password link.
        # Change "https://yourfrontenddomain.com" to your actual front-end domain.
        FRONTEND_URL = "https://meetyourfan.io"  # better: put in settings via env
        reset_link = f"{FRONTEND_URL}/reset-password/{uid}/{token}"

        # Plain-text fallback message (in case HTML is not supported by the email client).
        plain_message = (
            f"Hello {user.username},\n\n"
            f"Click the link below to reset your password:\n"
            f"{reset_link}\n\n"
            "If you didn't request a password reset, please ignore this email."
        )

        # Render the HTML template with context.
        context = {
            "username": user.username,
            "reset_link": reset_link
        }
        html_message = render_to_string("reset_password_email.html", context)

        try:
            # built-in send_mail() uses the settings configured in settings.py
            send_mail(
                subject="Password Reset Request",
                message=plain_message,  # plain text fallback
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                fail_silently=False,
                html_message=html_message,  # HTML content
            )
        except Exception as e:
            # Return an error if sending fails.
            return Response({"error": f"Failed to send reset email. Error: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"message": "Password reset link sent to your email."}, status=status.HTTP_200_OK)

class ResetPasswordConfirmAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        uidb64 = request.data.get("uid")
        token = request.data.get("token")
        new_password = request.data.get("new_password")

        if not uidb64 or not token or not new_password:
            return Response(
                {"detail": "uid, token, and new_password are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # urlsafe_base64_decode: built-in django helper -> bytes
            uid = force_str(urlsafe_base64_decode(uidb64))
            # force_str: built-in django helper -> converts bytes to string
            user = User.objects.get(pk=uid)
        except Exception:
            return Response({"detail": "Invalid reset link."}, status=status.HTTP_400_BAD_REQUEST)

        token_generator = PasswordResetTokenGenerator()

        # check_token(): built-in -> validates token integrity + expiry rules
        if not token_generator.check_token(user, token):
            return Response({"detail": "Reset link is invalid or expired."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # validate_password(): Django built-in -> runs AUTH_PASSWORD_VALIDATORS
            validate_password(new_password, user=user)
        except ValidationError as e:
            return Response({"new_password": list(e.messages)}, status=status.HTTP_400_BAD_REQUEST)

        # set_password(): Django built-in -> hashes password properly
        user.set_password(new_password)
        user.save()

        return Response({"message": "Password has been reset successfully."}, status=status.HTTP_200_OK)


USERNAME_REGEX = "^[a-zA-Z0-9_.-]+$"

class CheckUsernameAvailabilityView(APIView):
    permission_classes = [] 
    authentication_classes = []

    def get(self, request):
        username = (request.query_params.get('username') or '').strip()

        if not username:
            return Response({'error': 'Username parameter is required.'}, status=status.HTTP_400_BAD_REQUEST)

        # re.fullmatch: built-in regex function that matches the ENTIRE string (safer than match here)
        if not re.fullmatch(USERNAME_REGEX, username):
            return Response({'available': False, 'message': 'Invalid username format.'}, status=status.HTTP_400_BAD_REQUEST)

        # exists(): Django ORM built-in method that returns True/False without fetching rows (fast)
        if User.objects.filter(username__iexact=username).exists():
            return Response({'available': False, 'message': 'Username is already taken.'}, status=status.HTTP_200_OK)

        return Response({'available': True, 'message': 'Username is available.'}, status=status.HTTP_200_OK)


class SendVerificationCodeView(APIView):
    permission_classes = [IsAuthenticated]  # Ensure user is authenticated

    def post(self, request):
        user = request.user
        send_to = request.data.get('type')  # 'email' or 'phone'
        """
        if not send_to:
            return Response({'error': 'Type is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            verification, _ = VerificationCode.objects.get_or_create(user=user)

            if send_to == 'email':
                code = verification.generate_code()
                verification.email_code = code
                verification.save()
                # Mock email sending
                print(f'Sent email verification code: {code} to {user.email}')
                return Response({'message': 'Email verification code sent.'}, status=status.HTTP_200_OK)

            elif send_to == 'phone':
                if not user.phone_number:
                    return Response({'error': 'Phone number not set for user.'}, status=status.HTTP_400_BAD_REQUEST)

                code = verification.generate_code()
                verification.phone_code = code
                verification.save()
                # Mock SMS sending
                print(f'Sent phone verification code: {code} to {user.phone_number}')
                return Response({'message': 'Phone verification code sent.'}, status=status.HTTP_200_OK)

            return Response({'error': 'Invalid type. Must be "email" or "phone".'}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        """

class VerifyCodeView(APIView):
    permission_classes = [IsAuthenticated]  # Enforce authentication

    def post(self, request):
        user = request.user  # Authenticated user
        code = request.data.get('code')
        verify_type = request.data.get('type')  # 'email' or 'phone'

        if not code or not verify_type:
            return Response({'error': 'Code and type are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            verification = VerificationCode.objects.get(user=user)

            if verify_type == 'email' and verification.email_code == code:
                verification.email_verified = True
                verification.email_code = None  # Clear the code
                verification.save()
                return Response({'message': 'Email verified successfully.'}, status=status.HTTP_200_OK)

            elif verify_type == 'phone' and verification.phone_code == code:
                verification.phone_verified = True
                verification.phone_code = None  # Clear the code
                verification.save()
                return Response({'message': 'Phone verified successfully.'}, status=status.HTTP_200_OK)

            return Response({'error': 'Invalid code or type.'}, status=status.HTTP_400_BAD_REQUEST)

        except VerificationCode.DoesNotExist:
            return Response({'error': 'Verification code not found.'}, status=status.HTTP_404_NOT_FOUND)


class ResendVerificationCodeView(APIView):
    permission_classes = [IsAuthenticated]  # Only authenticated users can access this view.

    def post(self, request):
        user = request.user  # Authenticated user from the request.
        resend_type = request.data.get('type')  # Expected to be 'email' or 'phone'.

        if not resend_type:
            return Response({'error': 'Type is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Retrieve or create a VerificationCode instance for the user.
            verification, _ = VerificationCode.objects.get_or_create(user=user)

            if resend_type == 'email':
                # Generate a new verification code using the model's method.
                code = verification.generate_code()
                verification.email_code = code
                verification.email_verified = False  # Reset email verification status.
                verification.email_sent_at = timezone.now()  # Get current time using built-in function.
                verification.expires_at = timezone.now() + timedelta(minutes=10)  # Set expiration to 10 minutes later.
                verification.save()  # Save the updated verification record.

                # Build the HTML message replicating your design.
                html_message = f"""
                <!DOCTYPE html>
                <html>
                <head>
                  <meta charset="UTF-8" />
                  <title>New Code for Email Verification</title>
                </head>
                <body style="margin: 0; padding: 0; background-color: #ffffff; font-family: Arial, sans-serif;">
                  <table width="100%" bgcolor="#ffffff" style="padding: 1rem 0;" border="0" cellspacing="0" cellpadding="0">
                    <tr>
                      <td align="center">
                        <table width="400" border="0" cellspacing="0" cellpadding="0"
                               style="background-color: #ffffff; border-radius: 30px; overflow: hidden; 
                                      border: 1px solid rgba(0, 0, 0, 0.1); box-shadow: 0 8px 20px rgba(0,0,0,0.1);">
                          <tr>
                            <td style="padding: 2rem;">
                              <div style="text-align: center; margin-bottom: 1.5rem;">
                                <img src="https://meetyourfans3bucket.s3.us-east-1.amazonaws.com/static/images_folder/MeetYourFanLogoHorizontal-v2.png" alt="Logo" style="max-width: 150px;">
                              </div>
                              <h2 style="font-size: 24px; color: #000; margin-bottom: 1rem; text-align: center;">
                                New Code for Email Verification
                              </h2>
                              <p style="font-size: 16px; color: #333; margin-bottom: 1rem; text-align: center;">
                                Thank you for registering! To complete your registration, please use the verification code below:
                              </p>
                              <div style="text-align: center; margin: 2rem 0;">
                                <span style="display: inline-block; background-color: #f0f0f0; color: #000; padding: 0.75rem 1.5rem; border-radius: 9999px; font-size: 20px; letter-spacing: 2px; font-weight: bold;">
                                  {code}
                                </span>
                              </div>
                              <p style="font-size: 14px; color: #555; text-align: center; line-height: 1.6;">
                                If you did not register for this account, please ignore this email.
                                <br/>
                                <em>This code will expire in 10 minutes.</em>
                              </p>
                            </td>
                          </tr>
                        </table>
                      </td>
                    </tr>
                  </table>
                </body>
                </html>
                """
                # send_mail is a built-in Django function to send emails.
                # The html_message parameter allows you to send rich HTML emails.
                try:
                    send_mail(
                        subject="Resend: Verify Your Email Address",
                        message=f"Your verification code is: {code}",  # Plain text fallback.
                        from_email=settings.DEFAULT_FROM_EMAIL,  # Sender email from settings.
                        recipient_list=[user.email],  # List of recipient emails.
                        fail_silently=False,
                        html_message=html_message  # The HTML version of the email.
                    )
                except Exception as e:
                    return Response(
                        {"error": f"Failed to send verification email: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

                return Response({'message': 'Email verification code resent.'}, status=status.HTTP_200_OK)

            elif resend_type == 'phone':
                if not user.phone_number:
                    return Response({'error': 'Phone number not set for user.'}, status=status.HTTP_400_BAD_REQUEST)

                code = verification.generate_code()
                verification.phone_code = code
                verification.phone_verified = False  # Reset phone verification status.
                verification.phone_sent_at = timezone.now()  # Record current time.
                verification.expires_at = timezone.now() + timedelta(minutes=10)  # Set expiration.
                verification.save()

                # Here you would integrate with your SMS provider.
                print(f"Resent phone verification code: {code} to {user.phone_number}")
                return Response({'message': 'Phone verification code resent.'}, status=status.HTTP_200_OK)

            return Response({'error': 'Invalid type. Must be "email" or "phone".'}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class EditContactInfoView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user  # Authenticated user
        contact_type = request.data.get('type')  # 'email' or 'phone'
        new_value = request.data.get('value')

        if not contact_type or not new_value:
            return Response({'error': 'Type and value are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            if contact_type == 'email':
                if User.objects.filter(email=new_value).exists():
                    return Response({'error': 'This email is already in use.'}, status=status.HTTP_400_BAD_REQUEST)

                user.email = new_value
                user.save()
                # Generate a new email verification code
                verification, _ = VerificationCode.objects.get_or_create(user=user)
                code = verification.generate_code()
                verification.email_code = code
                verification.email_verified = False  # Require re-verification
                verification.save()
                # Mock email sending
                print(f'Email updated to {new_value}, verification code: {code}')
                return Response({'message': 'Email updated and verification code sent.'}, status=status.HTTP_200_OK)

            elif contact_type == 'phone':
                user.phone_number = new_value
                user.save()
                # Generate a new phone verification code
                verification, _ = VerificationCode.objects.get_or_create(user=user)
                code = verification.generate_code()
                verification.phone_code = code
                verification.phone_verified = False  # Require re-verification
                verification.save()
                # Mock SMS sending
                print(f'Phone number updated to {new_value}, verification code: {code}')
                return Response({'message': 'Phone number updated and verification code sent.'}, status=status.HTTP_200_OK)

            return Response({'error': 'Invalid type. Must be "email" or "phone".'}, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if not refresh_token:
                return Response({'error': 'Refresh token is required.'}, status=400)

            # Blacklist the refresh token
            token = RefreshToken(refresh_token)
            token.blacklist()

            return Response({'message': 'User logged out successfully.'}, status=200)
        except Exception as e:
            return Response({'error': str(e)}, status=500)
        

class UserProfileUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request):
        user = request.user
        serializer = UserProfileUpdateSerializer(user, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)
    
    
class ProfileImageUploadView(APIView):
    parser_classes = [MultiPartParser, FormParser]  # for file uploads
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        profile = request.user.profile

        # Use a tiny serializer that only exposes the two image fields:
        serializer = ProfileImageSerializer(
            profile,
            data=request.data,
            partial=True                 # ← only update the provided fields
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=status.HTTP_200_OK)
    
    
# If you have separate FanProfile/InfluencerProfile, find the one that exists:
def get_user_profile_obj(user):
    # getattr: built-in to safely read attribute; returns default if missing
    # If your project uses a single Profile model, just return user.profile.
    for attr in ("fanprofile", "influencerprofile", "profile"):
        obj = getattr(user, attr, None)
        if obj:
            return obj
    return None

class DeleteProfilePictureView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        prof = get_user_profile_obj(request.user)
        if not prof or not getattr(prof, "profile_picture", None):
            return Response(status=status.HTTP_204_NO_CONTENT)

        # FieldFile.delete(): built-in on Django File/ImageField that deletes the
        # underlying file from the storage backend (S3 via django-storages)
        prof.profile_picture.delete(save=False)
        # set to empty/None to persist removal in DB
        prof.profile_picture = None
        prof.save(update_fields=["profile_picture"])  # update_fields: built-in to save only listed fields
        return Response(status=status.HTTP_204_NO_CONTENT)

class DeleteCoverPhotoView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        prof = get_user_profile_obj(request.user)
        if not prof or not getattr(prof, "cover_photo", None):
            return Response(status=status.HTTP_204_NO_CONTENT)

        prof.cover_photo.delete(save=False)  # physically deletes from S3
        prof.cover_photo = None
        prof.save(update_fields=["cover_photo"])
        return Response(status=status.HTTP_204_NO_CONTENT)

class InfluencersView(APIView):
    permission_classes = [AllowAny] 
    
    def get(self, request):
        # Start with the base query for influencers.
        queryset = User.objects.filter(user_type='influencer')
        
        # Exclude the current user if authenticated.
        if request.user.is_authenticated:
            queryset = queryset.exclude(id=request.user.id)
        
        # Order by date joined (descending) and then limit to 15 records.
        influencers = queryset.order_by('-date_joined')[:14]
        
        serializer = AllUserSerializer(influencers, many=True, context={'request': request})
        return Response({'influencers': serializer.data}, status=status.HTTP_200_OK)

class FansView(APIView):
    permission_classes = [AllowAny] 
    
    def get(self, request):
        # Start with the base query for fans.
        queryset = User.objects.filter(user_type='fan')
        
        # Exclude the logged-in fan from the results if authenticated.
        if request.user.is_authenticated:
            queryset = queryset.exclude(id=request.user.id)
        
        # Order by date joined (descending) and then limit to 15 records.
        fans = queryset.order_by('-date_joined')[:14]
        
        serializer = AllUserSerializer(fans, many=True, context={'request': request})
        return Response({'fans': serializer.data}, status=status.HTTP_200_OK)

class InfluencerDetailView(APIView):
    
    permission_classes = [AllowAny]
    
    def get(self, request, influencer_id):
        try:
            influencer = User.objects.get(id=influencer_id, user_type='influencer')
        except User.DoesNotExist:
            return Response({'error': 'Influencer not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = InfluencerSerializer(influencer, context={'request': request})  # Use InfluencerSerializer
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class FanDetailView(APIView):
    permission_classes = [AllowAny] 
    
    def get(self, request, fan_id):
        try:
            fan = User.objects.get(id=fan_id, user_type='fan')
        except User.DoesNotExist:
            return Response({'error': 'Fan not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = FanSerializer(fan, context={'request': request})  # Use FanSerializer
        return Response(serializer.data, status=status.HTTP_200_OK)
    
class UpdateProfileStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request):
        try:
            # Get the authenticated user's profile
            profile = request.user.profile
            serializer = ProfileStatusSerializer(profile, data=request.data, partial=True, context={'request': request})
            
            if serializer.is_valid():
                serializer.save()
                return Response({
                    'message': 'Profile status updated successfully.',
                    'status': serializer.data['status']
                }, status=status.HTTP_200_OK)
            
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        except Profile.DoesNotExist:
            return Response({'error': 'Profile not found.'}, status=status.HTTP_404_NOT_FOUND)

class InstagramConnectView(APIView):
    """
    This view initiates the Instagram OAuth flow by redirecting the user to Instagram’s authorization page.
    """
    permission_classes = [IsAuthenticated]  # Only authenticated users can link their Instagram.

    def get(self, request):
        # Instagram's OAuth authorization endpoint.
        instagram_auth_url = "https://api.instagram.com/oauth/authorize"

        # Retrieve your client credentials from settings.
        client_id = settings.INSTAGRAM_CLIENT_ID
        redirect_uri = settings.INSTAGRAM_REDIRECT_URI  # This URI must match your Instagram app settings.
        scope = "user_profile"  # Define the access scope. Adjust if needed.
        response_type = "code"  # 'code' indicates that we want an authorization code.

        # Build the complete authorization URL.
        auth_url = (
            f"{instagram_auth_url}?client_id={client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&scope={scope}"
            f"&response_type={response_type}"
        )
        # 'redirect()' is a Django shortcut that returns an HttpResponseRedirect to the specified URL.
        return redirect(auth_url)

class InstagramCallbackView(APIView):
    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer]  # This disables the browsable API for this view

    def get(self, request):
        code = request.query_params.get("code")
        if not code:
            return Response({"error": "No code returned"}, status=400)

        token_url = "https://api.instagram.com/oauth/access_token"
        data = {
            "client_id": settings.INSTAGRAM_CLIENT_ID,
            "client_secret": settings.INSTAGRAM_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": settings.INSTAGRAM_REDIRECT_URI,
            "code": code,
        }
        response = requests.post(token_url, data=data)
        token_data = response.json()

        access_token = token_data.get("access_token")
        instagram_user_id = token_data.get("user_id")

        if not access_token or not instagram_user_id:
            return Response(
                {"error": "Failed to retrieve access token from Instagram."},
                status=400
            )

        profile = request.user.profile
        profile.instagram_user_id = instagram_user_id
        profile.instagram_access_token = access_token
        profile.save()

        return Response({"message": "Instagram account linked successfully."})

#Only for testing reset password
from django.shortcuts import render, redirect
from django.views import View
from django.contrib import messages
from django.utils.http import urlsafe_base64_decode

class TestResetPasswordView(View):
    def get(self, request, uidb64, token):
        """
        Verify the uid and token, then render the reset password form.
        """
        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None

        token_generator = PasswordResetTokenGenerator()
        if user is not None and token_generator.check_token(user, token):
            # Valid link—render a form for the user to reset their password.
            return render(request, 'reset_password_test.html', {'uidb64': uidb64, 'token': token})
        else:
            # Invalid link.
            return render(request, 'reset_password_invalid.html')

    def post(self, request, uidb64, token):
        """
        Process the password reset form.
        """
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        if new_password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return redirect(request.path)

        try:
            uid = urlsafe_base64_decode(uidb64).decode()
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None

        token_generator = PasswordResetTokenGenerator()
        if user is not None and token_generator.check_token(user, token):
            user.set_password(new_password)
            user.save()
            messages.success(request, "Password reset successful. You can now log in.")
            # Redirect to login page or wherever appropriate.
            return redirect("https://testing.meetyourfan.io/authentication/login")

        else:
            return render(request, 'reset_password_invalid.html')

class SubscribeEmailAPIView(APIView):
    permission_classes = [AllowAny] 
    authentication_classes = []
    
    def post(self, request):
        email_value = request.data.get("email")
        if not email_value:
            return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if email already exists
        if Email.objects.filter(email=email_value).exists():
            return Response({"message": "Email already subscribed."}, status=status.HTTP_200_OK)
        
        serializer = EmailSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"message": "Email subscribed successfully.", "data": serializer.data},
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    
class UserDashboardAnalyticsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # Serialize user data (includes profile and verification code)
        user_data = UserSerializer(user, context={'request': request}).data

        # Total followers: count of Follower records where the authenticated user is being followed.
        total_followers = Follower.objects.filter(user=user).count()
        # Total following: count of Follower records where the authenticated user is following others.
        total_following = Follower.objects.filter(follower=user).count()

        response_data = {
            "user_data": user_data,
            "total_followers": total_followers,
            "total_following": total_following,
        }

        # If the user is a fan: fetch campaigns joined and won, most recent first.
        if user.user_type == 'fan':
            distinct_participations = Participation.objects.filter(fan=user)\
                .order_by('campaign', '-created_at')\
                .distinct('campaign')
            joined_campaigns = sorted(
                distinct_participations,
                key=lambda p: p.created_at,
                reverse=True
            )
            joined_campaigns_data = [
                BaseCampaignSerializer(participation.campaign, context={'request': request}).data
                for participation in joined_campaigns
            ]
            
            won_campaigns_qs = CampaignWinner.objects.filter(fan=user).order_by('-selected_at')
            won_campaigns = [
                BaseCampaignSerializer(cw.campaign, context={'request': request}).data
                for cw in won_campaigns_qs
            ]
            response_data["joined_campaigns"] = joined_campaigns_data
            response_data["won_campaigns"] = won_campaigns


        # If the user is an influencer: fetch campaigns created by the user, most recent first.
        elif user.user_type == 'influencer':
            created_campaigns_qs = Campaign.objects.filter(user=user).order_by('-created_at')
            created_campaigns = [
                BaseCampaignSerializer(campaign, context={'request': request}).data
                for campaign in created_campaigns_qs
            ]
            response_data["created_campaigns"] = created_campaigns

        return Response(response_data, status=200)

    
    
class SocialMediaLinkListCreateAPIView(APIView):
    """
    GET: Return all social media links for the authenticated user.
    POST: Create a new social media link for the authenticated user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, format=None):
        links = SocialMediaLink.objects.filter(user=request.user)
        serializer = SocialMediaLinkSerializer(links, many=True, context={'request': request})
        return Response(serializer.data, status=200)

    def post(self, request, format=None):
        serializer = SocialMediaLinkSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            # Automatically assign the link to the authenticated user.
            serializer.save(user=request.user)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)
    
    def get_object(self, pk, user):
        try:
            return SocialMediaLink.objects.get(pk=pk, user=user)
        except SocialMediaLink.DoesNotExist:
            return None

    def put(self, request, pk, format=None):
        link = self.get_object(pk, request.user)
        if not link:
            return Response({"error": "Link not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = SocialMediaLinkSerializer(link, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, pk, format=None):
        link = self.get_object(pk, request.user)
        if not link:
            return Response({"error": "Link not found."}, status=status.HTTP_404_NOT_FOUND)
        link.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)



class SocialMediaLinkDetailAPIView(APIView):
    """
    GET: Retrieve a specific social media link.
    PUT: Update a specific social media link.
    DELETE: Delete a specific social media link.
    """
    permission_classes = [IsAuthenticated]

    def get_object(self, pk, user):
        try:
            return SocialMediaLink.objects.get(pk=pk, user=user)
        except SocialMediaLink.DoesNotExist:
            return None

    def get(self, request, pk, format=None):
        link = self.get_object(pk, request.user)
        if not link:
            return Response({"detail": "Not found."}, status=404)
        serializer = SocialMediaLinkSerializer(link, context={'request': request})
        return Response(serializer.data, status=200)

    def put(self, request, pk, format=None):
        link = self.get_object(pk, request.user)
        if not link:
            return Response({"detail": "Not found."}, status=404)
        serializer = SocialMediaLinkSerializer(link, data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)

    def delete(self, request, pk, format=None):
        link = self.get_object(pk, request.user)
        if not link:
            return Response({"detail": "Not found."}, status=404)
        link.delete()
        return Response(status=204)



class UpdateEmailView(APIView):
    permission_classes = [IsAuthenticated]  # Only authenticated users can update their email.

    def post(self, request):
        # Get the new email from the request data.
        new_email = request.data.get("new_email")
        if not new_email:
            return Response(
                {"error": "New email is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = request.user
        # Check if the new email is the same as the current email.
        if user.email == new_email:
            return Response(
                {"error": "New email is the same as the current email."},
                status=status.HTTP_400_BAD_REQUEST
            )
        # Check if the new email is already in use.
        if User.objects.filter(email=new_email).exists():
            return Response(
                {"error": "This email is already in use."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Update the user's email.
            user.email = new_email
            user.save()  # The built-in save() method persists changes to the database.

            # Retrieve or create a VerificationCode instance for the user.
            verification, created = VerificationCode.objects.get_or_create(user=user)
            # Generate a new 6-digit verification code using the model's built-in method.
            code = verification.generate_code()
            verification.email_code = code
            verification.email_verified = False  # Reset verification status.
            verification.email_sent_at = timezone.now()  # timezone.now() gets the current datetime.
            # timedelta is used here to set the expiration time 10 minutes from now.
            verification.expires_at = timezone.now() + timedelta(minutes=10)
            verification.save()

            # Build the HTML email message replicating your provided design.
            html_message = f"""
            <!DOCTYPE html>
            <html>
            <head>
              <meta charset="UTF-8" />
              <title>Verify Your New Email Address</title>
            </head>
            <body style="margin: 0; padding: 0; background-color: #ffffff; font-family: Arial, sans-serif;">
              <table width="100%" bgcolor="#ffffff" style="padding: 1rem 0;" border="0" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="center">
                    <table width="400" border="0" cellspacing="0" cellpadding="0"
                           style="background-color: #ffffff; border-radius: 30px; overflow: hidden; 
                                  border: 1px solid rgba(0, 0, 0, 0.1); box-shadow: 0 8px 20px rgba(0,0,0,0.1);">
                      <tr>
                        <td style="padding: 2rem;">
                          <div style="text-align: center; margin-bottom: 1.5rem;">
                            <img src="https://meetyourfans3bucket.s3.us-east-1.amazonaws.com/static/images_folder/MeetYourFanLogoHorizontal-v2.png" alt="Logo" style="max-width: 150px;">
                          </div>
                          <h2 style="font-size: 24px; color: #000; margin-bottom: 1rem; text-align: center;">
                            Verify Your New Email Address
                          </h2>
                          <p style="font-size: 16px; color: #333; margin-bottom: 1rem; text-align: center;">
                            Your email has been updated. Please use the verification code below to verify your new email address:
                          </p>
                          <div style="text-align: center; margin: 2rem 0;">
                            <span style="display: inline-block; background-color: #f0f0f0; color: #000; padding: 0.75rem 1.5rem; border-radius: 9999px; font-size: 20px; letter-spacing: 2px; font-weight: bold;">
                              {code}
                            </span>
                          </div>
                          <p style="font-size: 14px; color: #555; text-align: center; line-height: 1.6;">
                            If you did not request this change, please contact our support immediately.
                            <br/>
                            <em>This code will expire in 10 minutes.</em>
                          </p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
            </body>
            </html>
            """

            # send_mail is Django's built-in function for sending emails.
            # The html_message parameter allows you to send a rich HTML email.
            send_mail(
                subject="Verify Your New Email Address",
                message=f"Your verification code is: {code}",  # Plain text fallback.
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[new_email],
                fail_silently=False,
                html_message=html_message
            )

            return Response(
                {"message": "Email updated. Verification code sent to new email."},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            
            
class GuestCampaignPurchaseView(APIView):
    permission_classes = [AllowAny] 
    authentication_classes = []
    
    def post(self, request):
       
        # 2) Validate registration fields
        serializer = RegisterSerializer(data={
            "username": request.data.get("name") or request.data.get("username"),
            "email":    request.data.get("email"),
            "password": request.data.get("password"),
        })

        if not serializer.is_valid():
            return Response({"errors": serializer.errors},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            # 3) Save the new user
            user = serializer.save()

            # 4) Fire off the smart-contract registration in the background
            # try:
            #     tx_hash = register_user_on_chain.delay(user.user_id)
            # except Exception as e:
            #     return Response(
            #         {"error": "Blockchain registration failed", "details": str(e)},
            #         status=status.HTTP_500_INTERNAL_SERVER_ERROR
            #     )
            # 5) Generate & send email verification code
            verification, _ = VerificationCode.objects.get_or_create(user=user)
            code = verification.generate_code()
            verification.email_code       = code
            verification.expires_at       = timezone.now() + timedelta(minutes=10)
            verification.email_sent_at    = timezone.now()
            verification.save()

            html_message  = render_to_string("verify_email.html", {
                "username": user.username,
                "verification_code": code
            })
            plain_message = f"Your verification code is: {code}"

            send_mail(
                subject      = "Verify Your Email",
                message      = plain_message,
                from_email   = settings.DEFAULT_FROM_EMAIL,
                recipient_list = [user.email],
                html_message = html_message,
                fail_silently = False
            )

            # 6) Issue JWT tokens
            refresh    = RefreshToken.for_user(user)
            user_data  = UserSerializer(user).data
            # tack on any extra fields you need:
            user_data["user_id"] = str(user.user_id) 

            return Response({
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "user": user_data,
                "message": "Registered! Verification code sent, and on‐chain registration queued.",
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {"error": "Server error", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class CoverFocalUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        prof = request.user.profile
        fx = float(request.data.get('cover_focal_x', prof.cover_focal_x))
        fy = float(request.data.get('cover_focal_y', prof.cover_focal_y))
        prof.cover_focal_x = max(0.0, min(100.0, fx))
        prof.cover_focal_y = max(0.0, min(100.0, fy))
        prof.save(update_fields=['cover_focal_x', 'cover_focal_y'])
        return Response(
            {'cover_focal_x': prof.cover_focal_x, 'cover_focal_y': prof.cover_focal_y},
            status=status.HTTP_200_OK
        )


def create_username_reset_token(user) -> str:
    """
    Create a one-time username reset token for the given user.
    """
    for _ in range(5):  # a few attempts to avoid rare collisions
        token = secrets.token_urlsafe(32)
        if not UsernameResetToken.objects.filter(token=token).exists():
            UsernameResetToken.objects.create(user=user, token=token)
            return token
    raise RuntimeError("Could not generate a unique username reset token")


def send_username_reassigned_email(user, old_username: str, new_username: str, reset_token: str) -> None:
    """
    Email the user that their username was reassigned, and give them
    a one-time link to pick a new username.
    """
    reset_url = f"{settings.FRONTEND_ORIGIN}/username/reset?token={reset_token}"

    subject = "Your MeetYourFan username has been updated"

    plain_message = (
        f"Hi {user.username},\n\n"
        f"Your previous username @{old_username} has been reassigned to a verified creator on MeetYourFan.\n"
        f"Your current username is now @{new_username}.\n\n"
        f"If you’d like to choose a new username, you can use this one-time link:\n"
        f"{reset_url}\n\n"
        "If you do nothing, your current username will stay as it is."
    )

    html_message = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8" />
      <title>Your MeetYourFan username has been updated</title>
    </head>
    <body style="margin:0; padding:0; background-color:#ffffff; font-family:Arial,sans-serif;">
      <table width="100%" bgcolor="#ffffff" style="padding:1rem 0;" border="0" cellspacing="0" cellpadding="0">
        <tr>
          <td align="center">
            <table width="400" border="0" cellspacing="0" cellpadding="0"
                   style="background-color:#ffffff; border-radius:30px; overflow:hidden;
                          border:1px solid rgba(0,0,0,0.1); box-shadow:0 8px 20px rgba(0,0,0,0.1);">
              <tr>
                <td style="padding:2rem;">
                  <div style="text-align:center; margin-bottom:1.5rem;">
                    <img src="https://meetyourfans3bucket.s3.us-east-1.amazonaws.com/static/images_folder/MeetYourFanLogoHorizontal-v2.png"
                         alt="MeetYourFan" style="max-width:150px;">
                  </div>
                  <h2 style="font-size:22px; color:#000; margin-bottom:1rem; text-align:center;">
                    Your username has been updated
                  </h2>
                  <p style="font-size:15px; color:#333; margin-bottom:1rem; text-align:center;">
                    Your previous username <strong>@{old_username}</strong> has been reassigned
                    to a verified creator on MeetYourFan.
                  </p>
                  <p style="font-size:15px; color:#333; margin-bottom:1.5rem; text-align:center;">
                    Your new username is now <strong>@{new_username}</strong>.
                  </p>
                  <div style="text-align:center; margin:2rem 0;">
                    <a href="{reset_url}"
                       style="display:inline-block; background-color:#6A0DAD; color:#ffffff;
                              padding:0.75rem 1.5rem; border-radius:9999px; font-size:15px;
                              text-decoration:none;">
                      Choose a different username
                    </a>
                  </div>
                  <p style="font-size:13px; color:#555; text-align:center; line-height:1.6;">
                    This is a one-time link. If you don’t change anything, your current username
                    will remain <strong>@{new_username}</strong>.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """

    send_mail(
        subject=subject,
        message=plain_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
        html_message=html_message,
    )



class UpdateUsernameView(APIView):
    """
    PATCH /api/profile/update-username/

    Used when:
      - IG success screen: user claims their Instagram username.
      - (Optionally) other flows that want to set a new username.

    Behaviour:
      - Validate new username format.
      - If someone else already has that username:
          * generate a new unique username for that old owner,
          * save it,
          * send them an email with a one-time reset link.
      - Then assign the requested username to the current user.
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        new_username = (request.data.get("username") or "").strip()
        user = request.user

        if not new_username:
            return Response(
                {"error": "Username is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not re.match(USERNAME_REGEX, new_username):
            return Response(
                {"error": "Invalid username format."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_username_lower = new_username.lower()

        # If it's already their current username, nothing to do.
        if user.username and user.username.lower() == new_username_lower:
            prof = getattr(user, "profile", None)
            data = {
                "username": user.username,
            }
            if prof:
                data["profile"] = ProfileSerializer(prof, context={"request": request}).data
            return Response(data, status=status.HTTP_200_OK)

        # Check if someone else currently owns that username
        existing_owner = (
            User.objects
            .filter(username__iexact=new_username)
            .exclude(pk=user.pk)
            .select_related("profile")
            .first()
        )

        if existing_owner:
            old_username = existing_owner.username

            # Derive a base from their profile name, or email prefix, or fallback
            base = None
            try:
                base = existing_owner.profile.name or None
            except Exception:
                base = None

            if not base:
                if existing_owner.email:
                    base = existing_owner.email.split("@")[0]
                else:
                    base = f"user{existing_owner.pk}"

            new_for_existing = generate_unique_username_for_user(base, skip_user_id=None)

            existing_owner.username = new_for_existing
            existing_owner.save(update_fields=["username"])

            # Create one-time reset token and email them
            reset_token = create_username_reset_token(existing_owner)
            send_username_reassigned_email(
                user=existing_owner,
                old_username=old_username,
                new_username=new_for_existing,
                reset_token=reset_token,
            )

            logger.info(
                "Reassigned username '%s' from user_id=%s to user_id=%s, "
                "old owner now '%s'",
                old_username,
                existing_owner.id,
                user.id,
                new_for_existing,
            )

        # Now we can safely assign the requested username to the current user
        user.username = new_username
        user.save(update_fields=["username"])

        prof = getattr(user, "profile", None)
        data = {
            "username": user.username,
        }
        if prof:
            data["profile"] = ProfileSerializer(prof, context={"request": request}).data

        return Response(data, status=status.HTTP_200_OK)



class UsernameResetByTokenView(APIView):
    """
    POST /api/profile/username-reset/

    Body:
      - token: the one-time token from the email
      - username: desired new username

    Behaviour:
      - validate token (exists, not used, not too old)
      - validate username format + availability
      - update user's username
      - mark token as used
    """
    permission_classes = [AllowAny] 
    authentication_classes = []
    
    def get(self, request):
        token = (request.query_params.get("token") or "").strip()
        if not token:
            return Response(
                {"valid": False, "error": "Token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            entry = UsernameResetToken.objects.get(token=token)
        except UsernameResetToken.DoesNotExist:
            return Response(
                {"valid": False, "error": "Invalid or expired link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Already used or older than 1 day
        if entry.used or entry.created_at < timezone.now() - timedelta(days=1):
            return Response(
                {"valid": False, "error": "This link has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({"valid": True}, status=status.HTTP_200_OK)

    def post(self, request):
        token = (request.data.get("token") or "").strip()
        new_username = (request.data.get("username") or "").strip()

        if not token or not new_username:
            return Response(
                {"error": "Both 'token' and 'username' are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            entry = UsernameResetToken.objects.select_related("user").get(token=token)
        except UsernameResetToken.DoesNotExist:
            return Response(
                {"error": "Invalid or expired link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # One-time + simple expiry window (e.g. 24h)
        if entry.used or entry.created_at < timezone.now() - timedelta(days=1):
            return Response(
                {"error": "This link has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not re.match(USERNAME_REGEX, new_username):
            return Response(
                {"error": "Invalid username format."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Don't let them steal someone else's username here.
        if User.objects.filter(username__iexact=new_username).exclude(pk=entry.user.pk).exists():
            return Response(
                {"error": "This username is already taken."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = entry.user
        user.username = new_username
        user.save(update_fields=["username"])

        entry.used = True
        entry.save(update_fields=["used"])

        prof = getattr(user, "profile", None)
        data = {"username": user.username}
        if prof:
            data["profile"] = ProfileSerializer(prof, context={"request": request}).data

        return Response(data, status=status.HTTP_200_OK)



class DeleteMyAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        user = request.user
        reason = request.data.get("reason", "")  # dict.get is built-in: returns value or default

        soft_delete_user(user, reason=reason)

        # 204 = success, no content
        return Response(status=status.HTTP_204_NO_CONTENT)