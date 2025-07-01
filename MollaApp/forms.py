from django import forms
from MollaApp.models import CustomUser


class ProductSearchForm(forms.Form):
    type = forms.CharField(required=False)
    size = forms.CharField(required=False)
    brand = forms.CharField(required=False)

class ProfileForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ['name','phone_number', 'address', 'dp_image']