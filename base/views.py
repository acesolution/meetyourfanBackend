from django.shortcuts import render
import json
from django.http import JsonResponse
from .models import Email

def index(request):
    return render(request, 'index.html')

def save_email(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        email = data.get('email')
        if email:
            try:
                # Check if the email already exists
                if Email.objects.filter(email=email).exists():
                    return JsonResponse({'status': 'error', 'message': 'Email already exists'}, status=400)

                # Save email to the database
                Email.objects.create(email=email)
                return JsonResponse({'status': 'success'}, status=200)
            except Exception as e:
                return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)
    
    
def privacy_policy(request):
    return render(request, 'privacy_policy.html')

def terms_service(request):
    return render(request, 'terms.html')

def data_deletion(request):
    return render(request, 'data_deletion.html')