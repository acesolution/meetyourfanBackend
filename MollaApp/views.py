from django.shortcuts import render
from MollaApp.models import *
from django.shortcuts import render, HttpResponse,redirect, get_object_or_404
from django.contrib import messages
import json
from django.db.models import Count
from django.http import HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from .models import CustomUser,Contact,Subscribe,Wish_list,Cart_product,Order,Checkout_cart_product
from Product.models import Product, Category, Size, Brand, Pet, SubCategory
from django.contrib.auth.models import auth
from django.contrib.auth.decorators import login_required
from .forms import ProductSearchForm, ProfileForm
import uuid
from django.utils.translation import gettext_lazy as _
from django.template.loader import render_to_string
from django.conf import settings
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

def pagination(products, request):
    paginator = Paginator(products, 50)  # Paginator object

    page_number = request.GET.get('page', 1)  # Get the requested page number
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        page_obj = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        page_obj = paginator.page(paginator.num_pages)
    
    return page_obj

def home(request):
    all_products = Product.objects.all()
    paginator = Paginator(all_products, 20)
    page_number = request.GET.get('page')
    pets_obj = Pet.objects.filter()
    try:
        products = paginator.page(page_number)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        products = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        products = paginator.page(paginator.num_pages)

    top_sales = Product.objects.all()[10:20]
    # Assuming categories_qs is a queryset containing all categories
    categories = Category.objects.all()
    # Dictionary to store products for each category
    products_by_category = {}

    # Iterate over each category
    for category in categories:
        # Filter products based on the current category
        category_products = Product.objects.filter(category=category)[100:120]
        # Store the filtered category_products in the dictionary
        products_by_category[category] = category_products

    
    slider_products = Product.objects.filter(is_slider=True)
    banner_products = Product.objects.filter(is_banner=True)
    sale_products = Product.objects.filter(tag__name__icontains='sale')
    top_rated_products = Product.objects.filter(tag__name__icontains='top rated')
    food_products = Product.objects.filter(category__name__icontains='food')
    treats_products = Product.objects.filter(category__name__icontains='treats')
    supplies_products = Product.objects.filter(category__name__icontains='supplies')
    category_obj = Category.objects.all()
    size_obj = Size.objects.all()
    brand_obj = Brand.objects.all()
    cart_size = request.session.get('quantity', 0)
    session_id = request.session.get('cart_id')
    cart_obj = Cart_product.objects.filter(session=session_id)
    context = {
        'supplies_products': supplies_products,
        'treats_products' : treats_products,
        'food_products':food_products,
        'slider_products' : slider_products,
        'banner_products' : banner_products,
        'sale_products': sale_products,
        'top_rated_products': top_rated_products,
        'products':products,
        'top_sales': top_sales,
        'category_obj': category_obj,
        'size_obj': size_obj,
        'brand_obj' : brand_obj,
        'cart_size': cart_size,
        'pets_obj': pets_obj,
        'cart_obj':cart_obj,
    }
    return render(request,'index-1.html', context)

def search_products(request):
    if request.method == 'GET':
        query = request.GET.get('search')
        cart_size = request.session.get('quantity', 0)
        pets_obj = Pet.objects.filter()
        category_obj = Category.objects.all()
        session_id = request.session.get('cart_id')
        cart_obj = Cart_product.objects.filter(session=session_id)
        if query:
            search_results = Product.objects.filter(name__icontains=query)
            page_obj = pagination(search_results, request)
            product_counter = len(search_results)
            return render(request, 'search_results.html', {'results': page_obj, 'product_counter': product_counter, 'cart_size': cart_size, 'category_obj': category_obj,'pets_obj': pets_obj,'cart_obj':cart_obj,})
    return render(request, 'search_results.html', {'results': None, 'product_counter': 0, 'category_obj': category_obj,'pets_obj': pets_obj,'cart_obj':cart_obj,})


def about(request):
    pets_obj = Pet.objects.filter()
    category_obj = Category.objects.all()
    session_id = request.session.get('cart_id')
    cart_obj = Cart_product.objects.filter(session=session_id)
    context ={
        'category_obj': category_obj,
        'pets_obj': pets_obj,
        'cart_obj':cart_obj,
    }
    return render(request,'about.html', context)   

def page_404(request):
	return render(request,'404.html')

def blog(request):
	return render(request,'blog.html')

def cart(request):
    session_id = request.session.get('cart_id')
    if session_id is not None:
        cart_products = Cart_product.objects.filter(session = session_id)
    else:
        cart_products=""
    cart_size = request.session.get('quantity', 0)
    context = {'cart_products': cart_products, 'cart_size': cart_size}
    return render(request,'cart.html',context)

def product_by_category(request, value):
    # Get the selected category object
    cat_obj = Category.objects.get(name=value)
    
    # Filter products by the selected category
    products = Product.objects.filter(category=cat_obj)
    
    category_counts = Category.objects.filter(products__in=products).annotate(product_count=Count('products'))
    subcategory_counts = SubCategory.objects.filter(products__in=products).annotate(product_count=Count('products'))
    brand_counts = Brand.objects.filter(products__in=products).annotate(product_count=Count('products'))
    pet_counts = Pet.objects.filter(products__in=products).annotate(product_count=Count('products'))

    
    # Additional query sets and context preparation
    category = Category.objects.filter()
    sub_category = SubCategory.objects.filter()
    page_obj = pagination(products, request)
    cart_size = request.session.get('quantity', 0)
    filter_variable = 'category'
    pets_obj = Pet.objects.filter()
    category_obj = Category.objects.all()
    session_id = request.session.get('cart_id')
    cart_obj = Cart_product.objects.filter(session=session_id)
    brands = Brand.objects.filter()    
    # Context dictionary with counts
    context = {
        'page_obj': page_obj,
        'brands': brands,
        'cart_size': cart_size,
        'category': category,
        'indicator': 0,
        'cat_obj': cat_obj,
        'sub_category': sub_category,
        'filter_variable': filter_variable,
        'category_obj': category_obj,
        'pets_obj': pets_obj,
        'cart_obj': cart_obj,
        'category_counts': category_counts,
        'subcategory_counts': subcategory_counts,
        'pet_counts': pet_counts,
        'brand_counts':brand_counts,
    }
    
    return render(request, 'category.html', context)

def category_product(request):
    cart_size = request.session.get('quantity', 0)
    indicator = 0
    session_id = request.session.get('cart_id')
    cart_obj = Cart_product.objects.filter(session=session_id)
    category_counts = Category.objects.annotate(product_count=Count('products'))
    subcategory_counts = SubCategory.objects.annotate(product_count=Count('products'))
    brand_counts = Brand.objects.annotate(product_count=Count('products'))
    pet_counts = Pet.objects.annotate(product_count=Count('products'))
    pets_obj = Pet.objects.filter()
    category_obj = Category.objects.filter()
    context = {
        'cart_size' : cart_size,
        'indicator':indicator,
        'cart_obj':cart_obj,
        'category_counts':category_counts,
        'subcategory_counts': subcategory_counts,
        'brand_counts': brand_counts,
        'pet_counts': pet_counts,
        'pets_obj':pets_obj,
        'category_obj': category_obj
    }
    return render(request,'category.html', context)

def pets_product(request, value):
    pet_obj = Pet.objects.get(name=value)
    products = Product.objects.filter(pets = pet_obj)
    # Get unique brands associated with the products in the category
    brands = Brand.objects.filter()
    category = Category.objects.filter()
    page_obj = pagination(products, request)
    cart_size = request.session.get('quantity', 0)
    indicator = 1
    sub_category = SubCategory.objects.filter()
    filter_variable = 'pets'
    pets_obj = Pet.objects.filter()
    category_obj = Category.objects.all()
    session_id = request.session.get('cart_id')
    cart_obj = Cart_product.objects.filter(session=session_id)
    # Annotate counts for each category, subcategory, brand, and pet within the filtered products
    category_counts = Category.objects.filter(products__in=products).annotate(product_count=Count('products'))
    subcategory_counts = SubCategory.objects.filter(products__in=products).annotate(product_count=Count('products'))
    brand_counts = Brand.objects.filter(products__in=products).annotate(product_count=Count('products'))
    pet_counts = Pet.objects.filter(products__in=products).annotate(product_count=Count('products'))

    context = {
        'page_obj': page_obj,
        'brands': brands,
        'cart_size' : cart_size,
        'category':category,
        'indicator':indicator,
        'sub_category': sub_category,
        'filter_variable': filter_variable,
        'pet_obj':pet_obj,
        'category_obj': category_obj,
        'pets_obj': pets_obj,
        'cart_obj':cart_obj,
        'category_counts': category_counts,
        'subcategory_counts': subcategory_counts,
        'pet_counts': pet_counts,
        'brand_counts':brand_counts,
    }
    return render(request,'category.html', context)

def checkout_view(request):
    value = request.GET.get('value')
    session_id = request.session.get('cart_id')
    cart_products = Cart_product.objects.filter(session = session_id)
    checkout_cart = Checkout_cart_product.objects.get(id= value)
    cart_size = request.session.get('quantity', 0)
    pets_obj = Pet.objects.filter()
    category_obj = Category.objects.all()
    session_id = request.session.get('cart_id')
    cart_obj = Cart_product.objects.filter(session=session_id)
    context = {
        'cart_products': cart_products,
        'checkout_product': checkout_cart,
        'cart_size': cart_size,
        'value':value,
        'category_obj': category_obj,
        'pets_obj': pets_obj,
        'cart_obj':cart_obj,
    }
    return render(request,'checkout.html', context=context)

def checkout(request):
    if request.method == "POST":

        session_id = request.session.get('cart_id')
        cart_products = Cart_product.objects.filter(session = session_id)
        # Create an instance of Checkout_cart_product
        checkout_cart = Checkout_cart_product.objects.create(
            session=session_id,
        )
        shipping = request.POST.get('shipping')  # Retrieve 'shipping' from the POST data
        total = request.POST.get('total')
        # Add the queryset of Cart_product objects to the ManyToManyField
        checkout_cart.products.add(*cart_products)
        checkout_cart.shipping = shipping
        # Save the instance
        checkout_cart.save()
        # Return the checkout_cart ID in the JSON response
        return JsonResponse({'checkout_cart_id': checkout_cart.id, 'total': total})
        


def coming_soon(request):
	return render(request,'coming-soon.html')

def contact(request):
    if request.method == "POST":
        full_name = request.POST.get('name')
        phone_number = request.POST.get('phone_number')
        email = request.POST.get('email')
        msg = request.POST.get('msg')
        print(full_name, phone_number, email, msg)
        contact = Contact(full_name=full_name, phone_number=phone_number, email=email, msg=msg)
        contact.save()
        messages.success(request, 'Your message has been sent!')
    pets_obj = Pet.objects.filter()
    category_obj = Category.objects.all()
    session_id = request.session.get('cart_id')
    cart_obj = Cart_product.objects.filter(session=session_id)
    cart_size = request.session.get('quantity', 0)
    context = {
        'cart_size': cart_size,
        'category_obj': category_obj,
        'pets_obj': pets_obj,
        'cart_obj':cart_obj,
    }
    return render(request,'contact.html', context)

def dashboard(request):
	return render(request,'dashboard.html')

def faq(request):
	return render(request,'faq.html')
def signup(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        password = request.POST.get('password')

        # Validate form data
        if not (name and email and password):
            messages.error(request, 'Please fill in all the fields.')
            return render(request, 'signup.html')

        # Check if the user already exists
        if CustomUser.objects.filter(email=email).exists():
            messages.error(request, 'This email is already registered.')
            return render(request, 'signup.html')

        # Create the user
        user = CustomUser.objects.create_user(
            name=name,
            email=email,
            password=password
        )
        authenticated_user = auth.authenticate(email=email, password=password)
        # Authenticate and log in the user after successful creation
        if authenticated_user:
            auth.login(request, authenticated_user)
            return redirect('home')
        else:
            messages.error(request, 'Failed to log in the user after signup.')
            return render(request, 'signup.html')

    return render(request, 'signup.html')


def login(request):
    if request.method == "POST":
        session_key = request.session.get('cart_id', '')
        email = request.POST['email']
        password = request.POST['password']
        user = auth.authenticate(email=email,password=password)
        next_param = request.GET.get('next')
        if user is not None:
            auth.login(request,user)
            if 'cart_id' not in request.session:
                request.session['cart_id'] = str(uuid.uuid4())  # Generate a unique identifier for the cart


            new_session_key = request.session.get('cart_id')
            # Retrieve cart items associated with the previous session key
            cart_items = Cart_product.objects.filter(session=session_key)

            # Update these cart items with the new session key or associate them with the user
            for item in cart_items:
                item.session = new_session_key  # Update session key
                item.save()

            if not next_param:
                # 'next' parameter is empty
                # Handle accordingly, maybe redirect to a default page
                return redirect('home')
            else:
                return redirect('checkout')
    pets_obj = Pet.objects.filter()
    category_obj = Category.objects.all()
    session_id = request.session.get('cart_id')
    cart_obj = Cart_product.objects.filter(session=session_id)
    context = {
        'category_obj': category_obj,
        'pets_obj': pets_obj,
        'cart_obj':cart_obj,
    }
    return render(request, 'login.html', context)

def product(request, value):
    single_product = Product.objects.get(id=value)
    category = single_product.category
    related_products = Product.objects.filter(category=category)[:5]
    colors = single_product.color.all()  # Assumed to be a ManyToMany field or similar
    sizes = single_product.productsize_set.all()  # Assuming related model for sizes
    cart_size = request.session.get('quantity', 0)
    session_id = request.session.get('cart_id')
    cart_obj = Cart_product.objects.filter(session=session_id)
    pets_obj = Pet.objects.filter()
    category_obj = Category.objects.all()
    context = {
        'single_product': single_product,
        'related_products': related_products, 
        'colors': colors,
        'sizes': sizes,
        'cart_size': cart_size,
        'cart_obj':cart_obj,
        'category_obj': category_obj,
        'pets_obj': pets_obj,
    }
    return render(request, 'product.html', context)


def single(request):
	return render(request,'single.html')

def wishlist(request):
	return render(request,'wishlist.html')

def quickView(request):
	return render(request,'quickView.html')

def subscribe(request):
    if request.method == "POST":
        email = request.POST.get('email')
        if Subscribe.objects.filter(email=email).exists():
            messages.error(request, 'You are already subscribed.')
        else:
            subscribe_data = Subscribe(email=email)
            subscribe_data.save()
            messages.success(request, 'Successfully subscribed!')
        return redirect('home')  # Change 'subscribe' to your actual subscription URL name
    # return render(request, 'subscribe.html', {'form': form})
    #     subscribe_data = Subscribe(email=email)
    #     subscribe_data.save()
    #     messages.success(request, 'Your message has been sent!')
    # return redirect('home')

def update_profile(request):
    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            return redirect('profile')
    else:
        form = ProfileForm(instance=request.user)
    cart_size = request.session.get('quantity', 0)
    language = request.session.get('django_language')
    return render(request, 'profile1.html', {'form': form , 'cart_size': cart_size, 'language': language})

def logout(request):
    auth.logout(request)
    return redirect('home')

def save_product(request):
    if request.method == 'POST':
        id = request.POST.get('id')
        product_obj = Product.objects.get(id=id)
        size = request.POST.get('size')
        color = request.POST.get('color')
        quantity = request.POST.get('quantity')
        price = request.POST.get('price')
        # Get the session ID from the request object
        if 'cart_id' not in request.session:
            request.session['cart_id'] = str(uuid.uuid4())  # Generate a unique identifier for the cart
    
        session_id = request.session.get('cart_id')
        existing_quantity = request.session.get('quantity', 0)  # Get the existing quantity from the session or default to 0
        total_quantity = int(existing_quantity) + int(quantity)  # Calculate the total quantity
        request.session['quantity'] = total_quantity  # Save the total quantity in the session
        Cart_product.objects.create(
            product = product_obj,
            session = session_id,
            size=size,
            color = color,
            quantity=quantity,
            price=price,
        )
        
        return JsonResponse({'message': 'Product and form data saved successfully!', 'cart_id':session_id})
    else:
        return JsonResponse({'message': 'Invalid request'}, status=400)

def delete_product(request):
    if request.method == 'POST':
        try:
            product_id = request.POST.get('id')
            cart_size = request.session.get('quantity')
            quantity = request.POST.get('quantity')
            updated_size = int(cart_size) - int(quantity)
            request.session['quantity'] = updated_size
            # Delete the product from the database
            Cart_product.objects.get(id=product_id).delete()
            return JsonResponse({'message': 'Product deleted successfully'}, status=200)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


def checkout_product(request):
    if request.method == 'POST':
        session = request.session.get('cart_id', '0')
        cart_obj = Cart_product.objects.filter(session=session)

        return JsonResponse({'message': 'Order placed successfully!'})
    else:
        return JsonResponse({'message': 'Invalid request'}, status=400)
    
def order_placed(request):
    if request.method == 'POST':
        session = request.session.get('cart_id')
        name = request.POST.get('name')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        address = request.POST.get('address')
        country = request.POST.get('country')
        city = request.POST.get('city')
        zipcode = request.POST.get('zipcode')
        payment_method = request.POST.get('payment_method')
        total_price = request.POST.get('total')
        id = request.POST.get('id')
        product = Checkout_cart_product.objects.get(id=id)
        order = Order.objects.create(
            session=session,  # Replace with your session value
            product=product,  # Replace with your Checkout_cart_product object
            name = name,
            email=email,
            phone_number=phone,
            address=address,
            payment_method=payment_method,
            total_price=total_price,  # Assuming total_amount is a DecimalField
            country=country,
            city=city,
            postal_code=zipcode
        )

        order.save()

        session_id = request.session.get('cart_id')
        Cart_product.objects.filter(session = session_id).delete()
        cart_size = request.session.get('quantity', 0)
        request.session['quantity'] = 0

        return render(request,'order_placed.html',{'cart_size': cart_size})
    else:
        return JsonResponse({'message': 'Invalid request'}, status=400)

def update_quantity(request):
    if request.POST:
        product_id = request.POST.get('product_id')
        new_quantity = request.POST.get('new_quantity')
        # Perform validation, retrieve the product, and update the quantity
        # Sample logic (replace with your own)
        product = Cart_product.objects.get(id=product_id)
        product.quantity = new_quantity
        product.save()

        return JsonResponse({'success': True})  # Send a success response

    return JsonResponse({'success': False})  # Send a failure response if not an AJAX request


def filtered_products(request):
    # Get filter values from the request
    print(request.GET)
    category_ids = request.GET.getlist('category[]')
    pet_ids = request.GET.getlist('pets[]')
    brand_ids = request.GET.getlist('brands[]')
    sub_category_ids = request.GET.getlist('sub_category[]')
    min_price = int(request.GET.get('min_price'))  # Get minimum price
    max_price = int(request.GET.get('max_price'))  # Get maximum price
    selected_categories = []
    selected_pets = []
    selected_brands = []
    selected_sub_categories = []

    # Start filtering products based on the received filter values
    products = Product.objects.all()
    if category_ids[0] != '':
        # Split the comma-separated string into a list of IDs
        category_id_list = category_ids[0].split(',')
        
        # Filter products by selected categories
        products = products.filter(category__id__in=category_id_list)
        selected_categories = Category.objects.filter(id__in=category_id_list)
    
    if pet_ids[0] != '':
        # Split the comma-separated string into a list of IDs
        pet_id_list = pet_ids[0].split(',')
        # Filter products by selected pets
        products = products.filter(pets__id__in=pet_id_list)
        selected_pets = Pet.objects.filter(id__in=pet_id_list)
        
    if brand_ids[0] != '':
        # Split the comma-separated string into a list of IDs
        brand_id_list = brand_ids[0].split(',')
        # Filter products by selected brands
        products = products.filter(brand__id__in=brand_id_list)
        selected_brands = Brand.objects.filter(id__in=brand_id_list)
    
    if sub_category_ids[0] != '':
        # Split the comma-separated string into a list of IDs
        sub_category_id_list = sub_category_ids[0].split(',')
        # Filter products by selected sub-categories
        products = products.filter(sub_category__id__in=sub_category_id_list)
        selected_sub_categories = SubCategory.objects.filter(id__in=sub_category_id_list),
    
    if min_price is not None and max_price is not None:
        # Filter products by price range
        products = products.filter(default_price__gte=min_price, default_price__lte=max_price)
    # Perform pagination
    page_obj = pagination(products, request)
    # Prepare context for rendering HTML template
    context = {
        'page_obj': page_obj,
        'selected_categories': selected_categories,
        'selected_pets': selected_pets,
        'selected_brands': selected_brands,
        'selected_sub_categories': selected_sub_categories,
    }
    
    # Render the HTML template with the filtered products and other context
    html = render_to_string('filtered_products_template.html', context, request=request)
    
    # Return the HTML as a JSON response
    return JsonResponse({'html': html})
