from django.db import models
from django.contrib.auth.models import AbstractUser
from .manager import UserManager
from Product.models import Product

# Create your models here.

"""
class CustomUser(AbstractUser):
    username = None

    name= models.CharField(max_length=60,null=True)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=30,unique=True,null=True)
    address= models.CharField(max_length=600,null=True)
    dp_image= models.ImageField(upload_to='profile_images/', blank=True, null=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['phone_number']"""

class Contact(models.Model):
    full_name = models.CharField(max_length=50)
    phone_number = models.CharField(max_length=50)
    email = models.EmailField()
    msg= models.CharField(max_length=6000)

    def __str__(self):
        return self.full_name

class Subscribe(models.Model):
    email = models.EmailField(unique=True,max_length=200)

    def __str__(self):
        return self.email



class Wish_list(models.Model):
    name = models.CharField(max_length=1000)
    price = models.DecimalField(max_digits=100, decimal_places=2)
    image = models.ImageField()

    def __str__(self):
        return self.name


class Cart_product(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    session = models.CharField(max_length=256)
    size = models.CharField(max_length=50, blank=True, null=True)
    color = models.CharField(max_length=50, blank=True, null=True)
    quantity = models.PositiveIntegerField(default=1)
    price = models.FloatField()

class Checkout_cart_product(models.Model):
    session = models.CharField(max_length=256)
    products = models.ManyToManyField(Cart_product, related_name="products")
    shipping = models.FloatField(null=True ,blank=True)

class Order(models.Model):
    session = models.CharField(max_length=250)
    product = models.ForeignKey(Checkout_cart_product, on_delete=models.CASCADE)
    name = models.CharField(max_length=250)
    email = models.EmailField()
    phone_number = models.CharField(max_length=20)
    address = models.TextField()
    payment_method = models.CharField(max_length=50)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    country = models.CharField(max_length=50)
    city = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=50)