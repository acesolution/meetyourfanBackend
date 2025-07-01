from django.db import models
from django.utils.text import slugify
from django.utils.crypto import get_random_string

class Category(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, blank=True, null=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        # Generate a unique slug if the name exists and slug is not provided
        if self.name and not self.slug:
            # Use slugify to convert the name to a slug
            new_slug = slugify(self.name)

            # Check if the slug already exists
            if Category.objects.filter(slug=new_slug).exists():
                # If slug exists, generate a unique slug by appending random string
                new_slug += '-' + get_random_string(length=4)
            
            self.slug = new_slug
        
        super().save(*args, **kwargs)

class Color(models.Model):
    name = models.CharField(max_length=255)
    hex_value = models.CharField(max_length=7)  # hex code for the color

    class Meta:
        ordering = ('name', 'hex_value')

    def __str__(self):
        return self.name

class Season(models.Model):
    name = models.CharField(max_length=255)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name

class Brand(models.Model):
    name = models.CharField(max_length = 255)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name
    
class ProductImages(models.Model):
    img = models.ImageField(max_length=255)

class ProductTag(models.Model):
    name = models.CharField(max_length=50)
    sale_percent = models.IntegerField(blank=True, null=True)
    
    def __str__(self):
        return self.name

class SubCategory(models.Model):
    name = models.CharField(max_length=50)
    
    def __str__(self):
        return self.name

class Pet(models.Model):
    name = models.CharField(max_length=100)
    img = models.ImageField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.name

class Size(models.Model):
    name = models.CharField(max_length=255)
    
    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name

def get_default_tag():
    # Your logic to get the default tag
    # e.g., return ProductTag.objects.get(name='default-tag')
    return ProductTag.objects.get_or_create(name='Featured')

class Product(models.Model):
    category = models.ForeignKey(Category,related_name='products', on_delete=models.CASCADE)
    sub_category = models.ForeignKey(SubCategory,related_name='products', on_delete=models.CASCADE)
    pets = models.ForeignKey(Pet,related_name='products', on_delete=models.CASCADE)
    brand = models.ForeignKey(Brand,related_name='products', on_delete=models.CASCADE,blank=True, null=True)
    balance_code = models.CharField(max_length=255, blank=True, null=True)
    season = models.ForeignKey(Season, on_delete=models.CASCADE, blank=True, null=True)
    outer_material = models.CharField(max_length=255, blank=True, null=True)
    sizes = models.ManyToManyField(Size, through='ProductSize')
    tag = models.ForeignKey(ProductTag, on_delete=models.CASCADE, blank=True, null=True, default=get_default_tag)    
    color = models.ManyToManyField(Color, blank=True)
    name = models.CharField(max_length=1000, blank=True, null=True) 
    slug = models.SlugField(max_length=1000, unique=True, blank=True, null=True)
    default_price = models.FloatField()
    description = models.TextField(blank=True, null=True)
    image = models.ManyToManyField(ProductImages)
    is_slider = models.BooleanField(default=False)
    is_banner = models.BooleanField(default=False)
    
    create_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ('-create_at',)

    def save(self, *args, **kwargs):
        # Generate a unique slug if the name exists and slug is not provided
        if self.name and not self.slug:
            # Use slugify to convert the name to a slug
            new_slug = slugify(self.name)

            # Check if the slug already exists
            if Product.objects.filter(slug=new_slug).exists():
                # If the slug exists, generate a unique slug by appending a random string
                new_slug += '-' + get_random_string(length=4)

            # Set the slug
            self.slug = new_slug

        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    
class ProductSize(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    size = models.ForeignKey(Size, on_delete=models.CASCADE)
    price = models.IntegerField()

    class Meta:
        unique_together = ('product', 'size')  # Ensure each product-size combination is unique

    def __str__(self):
        return f"{self.product.name} - {self.size.name} - {self.price}"
    
class Comment(models.Model):
    username = models.CharField(max_length=100)
    email = models.EmailField(max_length=200)
    cmt = models.CharField(max_length=600)

    def __str__(self):
        return self.username